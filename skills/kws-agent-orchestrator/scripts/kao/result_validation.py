from __future__ import annotations

from .models import RESULT_SCHEMA


class ResultValidationError(ValueError):
    pass


def validate_worker_result(payload: dict[str, object]) -> dict[str, object]:
    required = {"schema", "worker_id", "task_id", "role", "status", "changed_files", "summary", "method_audit"}
    missing = sorted(required - set(payload))
    if missing:
        raise ResultValidationError("missing worker result fields: " + ", ".join(missing))
    if payload.get("schema") != RESULT_SCHEMA:
        raise ResultValidationError("invalid worker result schema")
    if payload.get("status") not in {"success", "failed", "blocked", "malformed"}:
        raise ResultValidationError("invalid worker status")
    if not isinstance(payload.get("changed_files"), list):
        raise ResultValidationError("changed_files must be a list")
    if not isinstance(payload.get("method_audit"), dict):
        raise ResultValidationError("method_audit must be an object")
    return payload
