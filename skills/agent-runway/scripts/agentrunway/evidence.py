from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .models import TaskSpec, WorkerResult


@dataclass(frozen=True)
class EvidenceDecision:
    allowed: bool
    reasons: tuple[str, ...]


def _value(source: Any, key: str) -> Any:
    if source is None:
        return None
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _status(source: Any) -> str | None:
    value = _value(source, "status")
    return str(value) if value is not None else None


def _normal_review_status(status: str | None) -> str | None:
    if status is None:
        return None
    if status in {"approved", "passed"}:
        return "approved"
    return status


def _normal_verification_status(status: str | None) -> str | None:
    if status is None:
        return None
    if status == "passed":
        return "passed"
    return status


def _verification_checks(candidate: Mapping[str, Any], verification_result: Mapping[str, Any] | None) -> list[dict[str, Any]] | None:
    raw_checks = candidate.get("verification_checks")
    if raw_checks is None and verification_result is not None:
        raw_checks = verification_result.get("checks")
    if raw_checks is None:
        return None
    if not isinstance(raw_checks, list):
        return []
    return [check for check in raw_checks if isinstance(check, dict)]


def validate_merge_evidence(
    *,
    task: TaskSpec | None = None,
    task_phase: str | None = None,
    candidate: Mapping[str, Any],
    worker_result: WorkerResult | Mapping[str, Any] | None = None,
    review_status: str | None = None,
    verification_status: str | None = None,
    verification_result: Mapping[str, Any] | None = None,
) -> EvidenceDecision:
    reasons: list[str] = []
    phase = task.phase if task is not None else task_phase
    candidate_status = str(candidate.get("status") or "")
    worker_status = str(candidate.get("worker_status") or _status(worker_result) or "")

    if worker_status == "simulated_success" or candidate_status.startswith("simulated"):
        reasons.append("simulated_result")

    normalized_review = _normal_review_status(review_status)
    normalized_verification = _normal_verification_status(verification_status)
    if normalized_review is not None and normalized_review != "approved":
        reasons.append("review_not_approved")
    if normalized_verification is not None and normalized_verification != "passed":
        reasons.append("verification_not_passed")

    if normalized_review is None and normalized_verification is None:
        if candidate_status == "review_approved":
            reasons.append("verification_not_passed")
        elif candidate_status != "merge_ready":
            reasons.append("not_merge_ready")

    if not candidate.get("commits"):
        reasons.append("missing_commit")
    if phase == "implementation" and not candidate.get("changed_files"):
        reasons.append("missing_changed_files")

    checks = _verification_checks(candidate, verification_result)
    acceptance_commands = tuple(task.acceptance_commands) if task is not None else ()
    if checks is not None and acceptance_commands:
        if not checks:
            reasons.append("acceptance_not_run")
        elif any(str(check.get("status") or "") != "passed" for check in checks):
            reasons.append("acceptance_not_passed")

    return EvidenceDecision(allowed=not reasons, reasons=tuple(dict.fromkeys(reasons)))
