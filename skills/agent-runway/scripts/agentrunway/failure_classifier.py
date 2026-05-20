from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Literal


class FailureClass(str, Enum):
    NEEDS_REBASE = "needs_rebase"
    NEEDS_FULL_CONTEXT = "needs_full_context"
    NEEDS_PLAN_FIX = "needs_plan_fix"
    NEEDS_SPLIT = "needs_split"
    NEEDS_IMPLEMENTER_RETRY = "needs_implementer_retry"
    NEEDS_INFRA_FIX = "needs_infra_fix"
    NEEDS_HUMAN_DECISION = "needs_human_decision"
    TERMINAL_REJECTED = "terminal_rejected"


@dataclass(frozen=True)
class FailureClassification:
    failure_class: str
    next_action: str
    consume_implementer_retry: bool
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    return str(value).lower()


def classify_gate_failure(
    *,
    gate: Literal["review", "verification"],
    status: str,
    result: dict[str, Any],
    candidate: dict[str, Any],
    task_acceptance_commands: list[str] | tuple[str, ...],
) -> FailureClassification:
    body = _text(result)
    changed_files = list(candidate.get("changed_files") or [])
    has_acceptance = bool(task_acceptance_commands)
    if status == "needs_context" or "need full" in body or "insufficient context" in body:
        return FailureClassification(
            failure_class=FailureClass.NEEDS_FULL_CONTEXT.value,
            next_action="rerun_review_full_tree" if gate == "review" else "rerun_verifier_full_tree",
            consume_implementer_retry=False,
            summary=f"{gate} requires broader context",
        )
    if "prior accepted" in body or "accepted work" in body or "latest checkpoint" in body or "stale base" in body:
        return FailureClassification(
            failure_class=FailureClass.NEEDS_REBASE.value,
            next_action="rerun_implementer_from_latest_checkpoint",
            consume_implementer_retry=False,
            summary=f"{gate} failure points to stale candidate base",
        )
    if "file claim" in body or "spec ref" in body or "acceptance command" in body or (changed_files and not has_acceptance and gate == "review"):
        return FailureClassification(
            failure_class=FailureClass.NEEDS_PLAN_FIX.value,
            next_action="fix_plan",
            consume_implementer_retry=False,
            summary=f"{gate} failure points to plan metadata",
        )
    if status == "blocked" or "adapter" in body or "sandbox" in body or "environment" in body or "preflight" in body:
        return FailureClassification(
            failure_class=FailureClass.NEEDS_INFRA_FIX.value,
            next_action="fix_infrastructure",
            consume_implementer_retry=False,
            summary=f"{gate} failure is infrastructure-related",
        )
    if status in {"failed", "changes_requested"} and (changed_files or has_acceptance):
        return FailureClassification(
            failure_class=FailureClass.NEEDS_IMPLEMENTER_RETRY.value,
            next_action="rerun_implementer_with_gate_evidence",
            consume_implementer_retry=True,
            summary=f"{gate} failure is actionable inside task scope",
        )
    return FailureClassification(
        failure_class=FailureClass.TERMINAL_REJECTED.value,
        next_action="block_task",
        consume_implementer_retry=False,
        summary=f"{gate} returned terminal status {status}",
    )


def classify_merge_failure(*, previous_conflicts: int, error: str) -> FailureClassification:
    if previous_conflicts < 1:
        return FailureClassification(
            failure_class=FailureClass.NEEDS_REBASE.value,
            next_action="rerun_implementer_from_latest_checkpoint",
            consume_implementer_retry=False,
            summary=f"merge conflict can be retried from latest checkpoint: {error}",
        )
    return FailureClassification(
        failure_class=FailureClass.NEEDS_HUMAN_DECISION.value,
        next_action="write_decision_packet",
        consume_implementer_retry=False,
        summary=f"repeated merge conflict requires operator decision: {error}",
    )
