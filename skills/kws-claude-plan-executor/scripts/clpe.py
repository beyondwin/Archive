#!/usr/bin/env python3
"""CLPE - thin Claude plan executor: run / resume / inspect.

CLPE maintains one execution environment and verifies submitted facts.
The child Claude session's Superpowers owns all workflow semantics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = SKILL_ROOT / "templates" / "plan-result.schema.json"

SCRUB_EXACT = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT")
SCRUB_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")
DENY_TOOLS = (
    "Bash(git push*)",
    "Bash(git merge*)",
    "Bash(rm -rf /*)",
    "Bash(git reset --hard origin*)",
)
DEFAULT_TIMEOUT_SECONDS = 3600
TIMEOUT_CEILING = 7200
MAX_LAUNCHES = 5

EXIT_COMPLETED = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2
EXIT_RESUMABLE = 3

PROVIDER_BLOCKED = {
    "rate_limit": "provider_usage_blocked",
    "overloaded": "provider_unavailable",
    "server_error": "provider_unavailable",
    "authentication_failed": "provider_auth_blocked",
    "oauth_org_not_allowed": "provider_auth_blocked",
    "billing_error": "provider_auth_blocked",
}

_SHA_PATTERN = re.compile(r"[0-9a-f]{7,40}")


def validate_result_shape(obj):
    """Fail-closed shape check for the child's structured_output."""
    if not isinstance(obj, dict):
        return ["structured_output is not an object"]
    errors = []
    for key in ("status", "head_commit", "summary", "open_findings"):
        if key not in obj:
            errors.append(f"missing field: {key}")
    status = obj.get("status")
    if status not in ("completed", "blocked", "failed"):
        errors.append(f"invalid status: {status!r}")
    head = obj.get("head_commit")
    if not isinstance(head, str) or not _SHA_PATTERN.fullmatch(head):
        errors.append("head_commit is not a git sha")
    summary = obj.get("summary")
    if not isinstance(summary, str) or not summary:
        errors.append("summary is empty")
    findings = obj.get("open_findings")
    if not isinstance(findings, list) or any(
        not isinstance(item, str) for item in (findings or [])
    ):
        errors.append("open_findings is not a list of strings")
    if status == "blocked":
        blocker = obj.get("blocker")
        if (
            not isinstance(blocker, dict)
            or not blocker.get("kind")
            or not blocker.get("detail")
        ):
            errors.append("blocked result requires blocker.kind and blocker.detail")
    return errors
