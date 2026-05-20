from __future__ import annotations

from agentrunway.models import FileClaim, TaskSpec
from agentrunway.quality_policy import (
    candidate_count_for_task,
    conflict_decision,
    gate_retry_decision,
)


def _task(*, risk: str = "medium", acceptance: tuple[str, ...] = ("python -m pytest",)) -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Example",
        risk=risk,  # type: ignore[arg-type]
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim(path="src/example.py", mode="owned"),),
        acceptance_commands=acceptance,
    )


def test_candidate_count_defaults_to_two_for_high_risk_only() -> None:
    assert candidate_count_for_task(_task(risk="low")) == 1
    assert candidate_count_for_task(_task(risk="medium")) == 1
    assert candidate_count_for_task(_task(risk="high")) == 2


def test_review_changes_requested_retries_once_when_actionable() -> None:
    decision = gate_retry_decision(
        task=_task(),
        gate="review",
        status="changes_requested",
        result={"findings": [{"severity": "major", "body": "tighten tests"}]},
        candidate={"changed_files": ["src/example.py"]},
        previous_retries=0,
    )

    assert decision.action == "retry"
    assert decision.reason == "review_changes_requested"
    assert decision.outcome == "partial"


def test_review_changes_requested_retries_with_acceptance_command_context() -> None:
    decision = gate_retry_decision(
        task=_task(acceptance=("python -m pytest",)),
        gate="review",
        status="changes_requested",
        result={"findings": [{"severity": "major", "body": "tighten tests"}]},
        candidate={"changed_files": []},
        previous_retries=0,
    )

    assert decision.action == "retry"
    assert decision.reason == "review_changes_requested"
    assert decision.outcome == "partial"


def test_review_changes_requested_blocks_after_budget() -> None:
    decision = gate_retry_decision(
        task=_task(),
        gate="review",
        status="changes_requested",
        result={"findings": [{"severity": "major", "body": "tighten tests"}]},
        candidate={"changed_files": ["src/example.py"]},
        previous_retries=1,
    )

    assert decision.action == "block"
    assert decision.reason == "gate_budget_exhausted"
    assert decision.outcome == "failed"


def test_verifier_failed_with_acceptance_evidence_retries_once() -> None:
    decision = gate_retry_decision(
        task=_task(acceptance=("python -m pytest",)),
        gate="verification",
        status="failed",
        result={"checks": []},
        candidate={"changed_files": []},
        previous_retries=0,
    )

    assert decision.action == "retry"
    assert decision.reason == "verification_failed"
    assert decision.outcome == "partial"


def test_verifier_failed_without_actionable_signal_blocks() -> None:
    decision = gate_retry_decision(
        task=_task(acceptance=()),
        gate="verification",
        status="failed",
        result={"checks": []},
        candidate={"changed_files": []},
        previous_retries=0,
    )

    assert decision.action == "block"
    assert decision.reason == "verification_failed_not_actionable"


def test_verifier_failed_with_empty_check_payload_blocks() -> None:
    decision = gate_retry_decision(
        task=_task(acceptance=()),
        gate="verification",
        status="failed",
        result={"checks": [{}]},
        candidate={"changed_files": []},
        previous_retries=0,
    )

    assert decision.action == "block"
    assert decision.reason == "verification_failed_not_actionable"


def test_verifier_blocked_never_retries() -> None:
    decision = gate_retry_decision(
        task=_task(),
        gate="verification",
        status="blocked",
        result={"checks": [{"command": "python -m pytest", "status": "blocked"}]},
        candidate={"changed_files": ["src/example.py"]},
        previous_retries=0,
    )

    assert decision.action == "block"
    assert decision.reason == "verification_blocked"


def test_first_conflict_can_redispatch_but_repeated_conflict_requires_manual_action() -> None:
    first = conflict_decision(task_id="task_001", previous_conflicts=0)
    repeated = conflict_decision(task_id="task_001", previous_conflicts=1)

    assert first.action == "redispatch"
    assert first.reason == "merge_conflict"
    assert repeated.action == "manual_action"
    assert repeated.reason == "repeated_merge_conflict"
