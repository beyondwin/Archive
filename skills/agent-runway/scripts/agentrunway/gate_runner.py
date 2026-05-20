from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .failure_classifier import classify_gate_failure
from .models import TaskSpec
from .quality_policy import PolicyDecision, gate_retry_decision


GateAction = Literal[
    "continue",
    "retry_implementer",
    "redispatch_from_latest_checkpoint",
    "await_human_decision",
    "terminal_block",
]

_HUMAN_DECISION_FAILURE_CLASSES = {
    "needs_plan_fix",
    "needs_split",
    "needs_human_decision",
    "needs_infra_fix",
    "terminal_rejected",
}


@dataclass(frozen=True)
class GateOutcome:
    action: GateAction
    policy: PolicyDecision
    failure_class: str | None
    decision_packet_required: bool


class GateRunner:
    def decision_packet_payload(
        self,
        *,
        gate: str,
        status: str,
        result: dict[str, Any],
        candidate: dict[str, Any],
        next_action: str,
        policy_reason: str,
    ) -> dict[str, Any]:
        return {
            "gate": gate,
            "status": status,
            "result": result,
            "candidate": {
                "id": candidate["id"],
                "worker_id": candidate["worker_id"],
                "changed_files": candidate["changed_files"],
                "commits": candidate["commits"],
            },
            "next_action": next_action,
            "policy_reason": policy_reason,
        }

    def decide(
        self,
        *,
        task: TaskSpec,
        gate: Literal["review", "verification"],
        status: str,
        result: dict[str, Any],
        candidate: dict[str, Any],
        previous_retries: int,
    ) -> GateOutcome:
        if gate == "review" and status == "approved":
            return GateOutcome(
                action="continue",
                policy=PolicyDecision(action="continue", reason="review_approved", outcome="success"),
                failure_class=None,
                decision_packet_required=False,
            )
        if gate == "verification" and status == "passed":
            return GateOutcome(
                action="continue",
                policy=PolicyDecision(action="continue", reason="verification_passed", outcome="success"),
                failure_class=None,
                decision_packet_required=False,
            )

        classification = classify_gate_failure(
            gate=gate,
            status=status,
            result=result,
            candidate=candidate,
            task_acceptance_commands=list(task.acceptance_commands),
        )
        policy = gate_retry_decision(
            task=task,
            gate=gate,
            status=status,
            result=result,
            candidate=candidate,
            previous_retries=previous_retries,
        )
        if classification.failure_class in _HUMAN_DECISION_FAILURE_CLASSES:
            block_policy = policy
            if block_policy.action != "block":
                block_policy = PolicyDecision(action="block", reason=f"{gate}_{classification.failure_class}", outcome="failed")
            return GateOutcome(
                action="await_human_decision",
                policy=block_policy,
                failure_class=classification.failure_class,
                decision_packet_required=True,
            )
        if classification.failure_class == "needs_rebase":
            if previous_retries > 0:
                return GateOutcome(
                    action="await_human_decision",
                    policy=PolicyDecision(action="block", reason=f"{gate}_needs_rebase_repeated", outcome="failed"),
                    failure_class=classification.failure_class,
                    decision_packet_required=True,
                )
            return GateOutcome(
                action="redispatch_from_latest_checkpoint",
                policy=PolicyDecision(action="redispatch", reason=f"{gate}_needs_rebase", outcome="partial"),
                failure_class=classification.failure_class,
                decision_packet_required=False,
            )
        if policy.action == "retry":
            return GateOutcome(
                action="retry_implementer",
                policy=policy,
                failure_class=classification.failure_class,
                decision_packet_required=False,
            )
        return GateOutcome(
            action="terminal_block",
            policy=policy,
            failure_class=classification.failure_class,
            decision_packet_required=False,
        )
