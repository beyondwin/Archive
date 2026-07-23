from __future__ import annotations

import hashlib
import json
import re
from enum import IntEnum
from typing import Any

CONTRACT_VERSION = 1
FORMAT_VERSION = 1

RUN_STATUSES = frozenset(
    {"running", "recovering", "resumable", "blocked", "failed", "ready_for_integration"}
)
PLAN_STATUSES = frozenset({"pending", "running", "implemented"})
TASK_STATUSES = frozenset({"pending", "running", "reported_done"})
RUNNER_RUNTIME_CONTRACT = {
    "free_threaded": False,
    "implementation": "cpython",
    "managed_by": "uv",
    "requires_python": ">=3.13,<3.14",
}
FAILURE_TAXONOMY = frozenset(
    {
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
        "review_failed",
        "runtime_incompatible",
        "runtime_missing",
        "session_invalid",
        "session_resume_failed",
        "stall_expired",
        "state_integrity_failed",
        "verification_failed",
        "verification_timed_out",
    }
)

_FULL_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class ExitCode(IntEnum):
    READY = 0
    RESUMABLE = 2
    BLOCKED = 3
    FAILED = 4
    INVALID = 64
    INTEGRITY = 65
    INTERNAL = 70


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def require_full_sha(value: object) -> str:
    if not isinstance(value, str) or _FULL_SHA.fullmatch(value) is None:
        raise ValueError("value must be a full Git SHA")
    return value


def require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("value must be a SHA-256 digest")
    return value
