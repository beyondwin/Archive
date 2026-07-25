from __future__ import annotations

import hashlib
import json
import re
from enum import IntEnum
from typing import Any

CONTRACT_VERSION = FORMAT_VERSION = 2

RUN_STATUSES = frozenset(
    ("running", "recovering", "resumable", "blocked", "failed", "ready_for_integration")
)
PLAN_STATUSES = frozenset(("pending", "running", "implemented"))
TASK_STATUSES = frozenset()
NEXT_STRATEGIES = frozenset(("resume_root", "fresh_root", "block"))
RUNNER_RUNTIME_CONTRACT = {
    "implementation": "cpython",
    "requires_python": ">=3.13,<3.14",
    "managed_by": "uv",
    "free_threaded": False,
}
FAILURE_TAXONOMY = frozenset(
    (
        "controller_spawn_failed",
        "controller_transport_failed",
        "destructive_authorization_required",
        "external_authority_required",
        "input_changed_requires_new_run",
        "irreconcilable_requirements",
        "provider_auth_blocked",
        "provider_unavailable",
        "provider_usage_blocked",
        "recovery_exhausted",
        "runtime_incompatible",
        "runtime_missing",
        "session_invalid",
        "session_resume_failed",
        "stall_expired",
        "state_integrity_failed",
        "verification_failed",
        "verification_timed_out",
    )
)

_GIT_OBJECT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ExitCode(IntEnum):
    READY = 0
    RESUMABLE = 2
    BLOCKED = 3
    FAILED = 4
    INVALID = 64
    INTEGRITY = 65
    INTERNAL = 70


def canonical_json(value: Any) -> bytes:
    text = json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    return text.encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def require_full_sha(value: object) -> str:
    if not isinstance(value, str) or _GIT_OBJECT.fullmatch(value) is None:
        raise ValueError("value must be a full Git SHA")
    return value


def require_digest(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("value must be a SHA-256 digest")
    return value
