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


def validate_review_result(payload: dict[str, object]) -> dict[str, object]:
    required = {"schema", "worker_id", "task_id", "reviewed_worker_id", "status", "checks", "findings", "method_audit"}
    missing = sorted(required - set(payload))
    if missing:
        raise ResultValidationError("missing review result fields: " + ", ".join(missing))
    if payload["schema"] != "agentrunway.review_result.v1":
        raise ResultValidationError("invalid review result schema")
    if payload["status"] not in {"approved", "changes_requested", "rejected", "needs_context"}:
        raise ResultValidationError("invalid review status")
    review_mode = payload.get("review_mode")
    if review_mode is not None and review_mode not in {"diff", "full_tree"}:
        raise ResultValidationError("invalid review mode")
    findings = payload.get("findings")
    if payload["status"] == "approved" and isinstance(findings, list) and findings:
        raise ResultValidationError("approved review cannot include findings")
    return payload


def validate_verification_result(payload: dict[str, object]) -> dict[str, object]:
    required = {"schema", "worker_id", "task_id", "status", "checks", "method_audit"}
    missing = sorted(required - set(payload))
    if missing:
        raise ResultValidationError("missing verification result fields: " + ", ".join(missing))
    if payload["schema"] != "agentrunway.verification_result.v1":
        raise ResultValidationError("invalid verification result schema")
    if payload["status"] not in {"passed", "failed", "blocked"}:
        raise ResultValidationError("invalid verification status")
    return payload
