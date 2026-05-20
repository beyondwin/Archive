from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .models import TaskSpec

PolicyAction = Literal["retry", "block", "continue", "redispatch", "manual_action"]


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    reason: str
    outcome: Literal["success", "partial", "failed"]
    next_attempt: int | None = None


def candidate_count_for_task(task: TaskSpec) -> int:
    return 2 if task.risk == "high" else 1


def _has_actionable_review(task: TaskSpec, result: dict[str, Any], candidate: dict[str, Any]) -> bool:
    findings = result.get("findings")
    changed_files = candidate.get("changed_files")
    return bool(findings) and (bool(changed_files) or bool(task.acceptance_commands))


def _has_actionable_verification(task: TaskSpec, result: dict[str, Any], candidate: dict[str, Any]) -> bool:
    checks = result.get("checks")
    changed_files = candidate.get("changed_files")
    return bool(checks) or bool(changed_files) or bool(task.acceptance_commands)


def gate_retry_decision(
    *,
    task: TaskSpec,
    gate: Literal["review", "verification"],
    status: str,
    result: dict[str, Any],
    candidate: dict[str, Any],
    previous_retries: int,
) -> PolicyDecision:
    if gate == "review":
        if status == "approved":
            return PolicyDecision(action="continue", reason="review_approved", outcome="success")
        if status == "changes_requested" and previous_retries < 1 and _has_actionable_review(task, result, candidate):
            return PolicyDecision(
                action="retry",
                reason="review_changes_requested",
                outcome="partial",
                next_attempt=previous_retries + 2,
            )
        if status == "changes_requested":
            return PolicyDecision(action="block", reason="gate_budget_exhausted", outcome="failed")
        return PolicyDecision(action="block", reason="review_rejected", outcome="failed")

    if status == "passed":
        return PolicyDecision(action="continue", reason="verification_passed", outcome="success")
    if status == "blocked":
        return PolicyDecision(action="block", reason="verification_blocked", outcome="failed")
    if status == "failed" and previous_retries < 1 and _has_actionable_verification(task, result, candidate):
        return PolicyDecision(
            action="retry",
            reason="verification_failed",
            outcome="partial",
            next_attempt=previous_retries + 2,
        )
    if status == "failed":
        return PolicyDecision(action="block", reason="verification_failed_not_actionable", outcome="failed")
    return PolicyDecision(action="block", reason="verification_rejected", outcome="failed")


def conflict_decision(*, task_id: str, previous_conflicts: int) -> PolicyDecision:
    _ = task_id
    if previous_conflicts < 1:
        return PolicyDecision(
            action="redispatch",
            reason="merge_conflict",
            outcome="partial",
            next_attempt=previous_conflicts + 2,
        )
    return PolicyDecision(action="manual_action", reason="repeated_merge_conflict", outcome="failed")
