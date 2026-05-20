from __future__ import annotations

from agentrunway.failure_classifier import FailureClass, classify_gate_failure, classify_merge_failure


def test_review_needs_context_classifies_full_context() -> None:
    result = classify_gate_failure(
        gate="review",
        status="needs_context",
        result={"findings": [{"body": "Need full tree"}]},
        candidate={"changed_files": ["src/tool.py"]},
        task_acceptance_commands=["python -m pytest"],
    )

    assert result.failure_class == FailureClass.NEEDS_FULL_CONTEXT.value
    assert result.next_action == "rerun_review_full_tree"
    assert result.consume_implementer_retry is False


def test_review_mentions_accepted_work_classifies_rebase() -> None:
    result = classify_gate_failure(
        gate="review",
        status="changes_requested",
        result={"findings": [{"body": "Candidate misses prior accepted work from task_001"}]},
        candidate={"changed_files": ["skills/agent-runway/scripts/agentrunway/invocation.py"]},
        task_acceptance_commands=["python -m pytest"],
    )

    assert result.failure_class == FailureClass.NEEDS_REBASE.value
    assert result.next_action == "rerun_implementer_from_latest_checkpoint"
    assert result.consume_implementer_retry is False


def test_verifier_failed_command_classifies_implementer_retry() -> None:
    result = classify_gate_failure(
        gate="verification",
        status="failed",
        result={"checks": [{"command": "python -m pytest", "status": "failed"}]},
        candidate={"changed_files": ["src/tool.py"]},
        task_acceptance_commands=["python -m pytest"],
    )

    assert result.failure_class == FailureClass.NEEDS_IMPLEMENTER_RETRY.value
    assert result.next_action == "rerun_implementer_with_gate_evidence"
    assert result.consume_implementer_retry is True


def test_verifier_blocked_environment_classifies_infra_fix() -> None:
    result = classify_gate_failure(
        gate="verification",
        status="blocked",
        result={"checks": [{"command": "python -m pytest", "status": "blocked", "error": "adapter missing"}]},
        candidate={"changed_files": ["src/tool.py"]},
        task_acceptance_commands=["python -m pytest"],
    )

    assert result.failure_class == FailureClass.NEEDS_INFRA_FIX.value
    assert result.next_action == "fix_infrastructure"
    assert result.consume_implementer_retry is False


def test_missing_plan_metadata_classifies_plan_fix() -> None:
    result = classify_gate_failure(
        gate="review",
        status="changes_requested",
        result={"findings": [{"body": "file claim is missing for invocation.py"}]},
        candidate={"changed_files": ["skills/agent-runway/scripts/agentrunway/invocation.py"]},
        task_acceptance_commands=[],
    )

    assert result.failure_class == FailureClass.NEEDS_PLAN_FIX.value
    assert result.next_action == "fix_plan"


def test_first_merge_conflict_rebase_then_repeated_human_decision() -> None:
    first = classify_merge_failure(previous_conflicts=0, error="conflict in runner.py")
    repeated = classify_merge_failure(previous_conflicts=1, error="conflict in runner.py")

    assert first.failure_class == FailureClass.NEEDS_REBASE.value
    assert first.next_action == "rerun_implementer_from_latest_checkpoint"
    assert repeated.failure_class == FailureClass.NEEDS_HUMAN_DECISION.value
    assert repeated.next_action == "write_decision_packet"


def test_plan_lint_failure_classifies_plan_fix() -> None:
    from agentrunway.failure_classifier import classify_plan_failure

    result = classify_plan_failure(
        lint_result={
            "ok": False,
            "errors": [{"code": "forbidden_owned_path", "detail": "graphify-out is generated"}],
        }
    )

    assert result.failure_class == FailureClass.NEEDS_PLAN_FIX.value
    assert result.next_action == "fix_plan"
