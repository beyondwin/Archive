from __future__ import annotations

from agentrunway.evidence import validate_merge_evidence
from agentrunway.models import FileClaim, TaskSpec


def _task(*, phase: str = "implementation") -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Task",
        risk="medium",
        phase=phase,
        dependencies=(),
        spec_refs=("S1.1",),
        file_claims=(FileClaim("src/a.py", "owned"),),
        acceptance_commands=("pytest",),
    )


def _candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "id": 1,
        "task_id": "task_001",
        "worker_id": "worker-1",
        "status": "merge_ready",
        "commits": ["abc123"],
        "changed_files": ["src/a.py"],
    }
    candidate.update(overrides)
    return candidate


def test_merge_evidence_accepts_ready_candidate() -> None:
    decision = validate_merge_evidence(task=_task(), candidate=_candidate())

    assert decision.allowed is True
    assert decision.reasons == ()


def test_merge_evidence_rejects_missing_commit() -> None:
    decision = validate_merge_evidence(task=_task(), candidate=_candidate(commits=[]))

    assert decision.allowed is False
    assert "missing_commit" in decision.reasons


def test_merge_evidence_rejects_missing_changed_files_for_implementation() -> None:
    decision = validate_merge_evidence(task=_task(), candidate=_candidate(changed_files=[]))

    assert decision.allowed is False
    assert "missing_changed_files" in decision.reasons


def test_merge_evidence_rejects_unreviewed_candidate() -> None:
    decision = validate_merge_evidence(task=_task(), candidate=_candidate(), review_status="changes_requested")

    assert decision.allowed is False
    assert "review_not_approved" in decision.reasons


def test_merge_evidence_rejects_unverified_candidate() -> None:
    decision = validate_merge_evidence(task=_task(), candidate=_candidate(), verification_status="failed")

    assert decision.allowed is False
    assert "verification_not_passed" in decision.reasons


def test_merge_evidence_rejects_missing_acceptance_check_when_checks_are_available() -> None:
    decision = validate_merge_evidence(
        task=_task(),
        candidate=_candidate(),
        review_status="approved",
        verification_status="passed",
        verification_result={"checks": []},
    )

    assert decision.allowed is False
    assert "acceptance_not_run" in decision.reasons


def test_merge_evidence_rejects_failed_acceptance_check() -> None:
    decision = validate_merge_evidence(
        task=_task(),
        candidate=_candidate(),
        review_status="approved",
        verification_status="passed",
        verification_result={"checks": [{"command": "pytest", "status": "failed"}]},
    )

    assert decision.allowed is False
    assert "acceptance_not_passed" in decision.reasons


def test_merge_evidence_rejects_simulated_result() -> None:
    decision = validate_merge_evidence(
        task=_task(),
        candidate=_candidate(status="merge_ready", worker_status="simulated_success"),
    )

    assert decision.allowed is False
    assert "simulated_result" in decision.reasons
