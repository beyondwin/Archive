from __future__ import annotations

from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.durable_resume import plan_activity_resume
from agentrunway.workflow_store import ActivityStatus, WorkflowStore


def _store(tmp_path: Path) -> WorkflowStore:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    return WorkflowStore(db)


def test_resume_after_implement_completion_schedules_review(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.implement.001",
        idempotency_key="run-1:task_001:implement:001",
        task_id="task_001",
        activity_type="implement",
        input_refs={"checkpoint_id": "cp-000"},
    )
    store.complete_activity(
        activity_id="task_001.implement.001",
        status=ActivityStatus.COMPLETED,
        output_refs={"candidate_id": 7, "worker_result": "artifacts/task_001/worker_result.json"},
        failure_class=None,
    )

    plan = plan_activity_resume(run_id="run-1", db=store.db)

    assert plan["next_node"] == "task_001.review"
    assert plan["next_action"] == "schedule_review"
    assert plan["candidate_id"] == 7
    assert plan["reuse_completed_activity"] is True


def test_resume_after_review_approval_schedules_verification(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.review.001",
        idempotency_key="run-1:task_001:review:001",
        task_id="task_001",
        activity_type="review",
        input_refs={"candidate_id": 7},
    )
    store.complete_activity(
        activity_id="task_001.review.001",
        status=ActivityStatus.COMPLETED,
        output_refs={"candidate_id": 7, "review_status": "approved"},
        failure_class=None,
    )

    plan = plan_activity_resume(run_id="run-1", db=store.db)

    assert plan["next_node"] == "task_001.verification"
    assert plan["next_action"] == "schedule_verification"
    assert plan["candidate_id"] == 7


def test_resume_after_verification_success_schedules_merge(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.verification.001",
        idempotency_key="run-1:task_001:verification:001",
        task_id="task_001",
        activity_type="verification",
        input_refs={"candidate_id": 7},
    )
    store.complete_activity(
        activity_id="task_001.verification.001",
        status=ActivityStatus.COMPLETED,
        output_refs={"candidate_id": 7, "verification_status": "passed"},
        failure_class=None,
    )

    plan = plan_activity_resume(run_id="run-1", db=store.db)

    assert plan["next_node"] == "task_001.merge"
    assert plan["next_action"] == "schedule_merge"
    assert plan["candidate_id"] == 7


def test_resume_after_blocked_activity_waits_for_decision_packet(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.review.001",
        idempotency_key="run-1:task_001:review:001",
        task_id="task_001",
        activity_type="review",
        input_refs={"candidate_id": 7},
    )
    store.complete_activity(
        activity_id="task_001.review.001",
        status=ActivityStatus.BLOCKED,
        output_refs={"candidate_id": 7, "review_status": "changes_requested"},
        failure_class="needs_plan_fix",
    )
    store.create_decision_packet(
        run_id="run-1",
        decision_id="task_001.review.001.decision",
        task_id="task_001",
        failure_class="needs_plan_fix",
        summary="review failure points to plan metadata",
        payload={"candidate_id": 7},
    )

    plan = plan_activity_resume(run_id="run-1", db=store.db)

    assert plan["next_node"] == "task_001.review.001.decision"
    assert plan["next_action"] == "await_human_decision"
    assert plan["failure_class"] == "needs_plan_fix"
