from __future__ import annotations

from agentrunway.gate_runner import GateOutcome, GateRunner
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.quality_policy import PolicyDecision


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Task 1",
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1.1",),
        file_claims=(FileClaim("src/a.py", "owned"),),
        acceptance_commands=("python -m pytest",),
    )


def test_gate_runner_blocks_human_decision_class() -> None:
    outcome = GateRunner().decide(
        task=_task(),
        gate="review",
        status="changes_requested",
        result={"status": "changes_requested", "findings": [{"body": "file claim is missing"}]},
        candidate={"id": 1, "worker_id": "task_001-implementer-001", "changed_files": ["src/a.py"], "commits": ["abc"]},
        previous_retries=0,
    )

    assert outcome == GateOutcome(
        action="await_human_decision",
        policy=PolicyDecision(action="block", reason="review_needs_plan_fix", outcome="failed"),
        failure_class="needs_plan_fix",
        decision_packet_required=True,
    )


def test_gate_runner_retries_implementer_for_actionable_verifier_failure() -> None:
    outcome = GateRunner().decide(
        task=_task(),
        gate="verification",
        status="failed",
        result={"status": "failed", "checks": [{"command": "python -m pytest", "status": "failed"}]},
        candidate={"id": 1, "worker_id": "task_001-implementer-001", "changed_files": ["src/a.py"], "commits": ["abc"]},
        previous_retries=0,
    )

    assert outcome.action == "retry_implementer"
    assert outcome.failure_class == "needs_implementer_retry"
    assert outcome.decision_packet_required is False


def test_gate_runner_redispatches_rebase_before_generic_retry() -> None:
    outcome = GateRunner().decide(
        task=_task(),
        gate="review",
        status="changes_requested",
        result={"status": "changes_requested", "findings": [{"body": "prior accepted work changed this base"}]},
        candidate={"id": 1, "worker_id": "task_001-implementer-001", "changed_files": ["src/a.py"], "commits": ["abc"]},
        previous_retries=0,
    )

    assert outcome.action == "redispatch_from_latest_checkpoint"
    assert outcome.policy == PolicyDecision(action="redispatch", reason="review_needs_rebase", outcome="partial")
    assert outcome.failure_class == "needs_rebase"
    assert outcome.decision_packet_required is False


def test_gate_runner_blocks_repeated_rebase_after_budget_is_consumed() -> None:
    outcome = GateRunner().decide(
        task=_task(),
        gate="review",
        status="changes_requested",
        result={"status": "changes_requested", "findings": [{"body": "prior accepted work changed this base"}]},
        candidate={"id": 1, "worker_id": "task_001-implementer-001", "changed_files": ["src/a.py"], "commits": ["abc"]},
        previous_retries=1,
    )

    assert outcome == GateOutcome(
        action="await_human_decision",
        policy=PolicyDecision(action="block", reason="review_needs_rebase_repeated", outcome="failed"),
        failure_class="needs_rebase",
        decision_packet_required=True,
    )
