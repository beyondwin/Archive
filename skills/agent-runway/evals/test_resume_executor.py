from __future__ import annotations

from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.models import TaskSpec
from agentrunway.resume_executor import ResumeExecutor
from agentrunway.resume_planner import ResumeAction, plan_resume_actions
from agentrunway.workflow_store import ActivityStatus, WorkflowStore


def _store(tmp_path: Path) -> WorkflowStore:
    return WorkflowStore(AgentRunwayDb.open(tmp_path / "state.sqlite"))


def test_resume_planner_keeps_dry_run_side_effect_free(tmp_path: Path) -> None:
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
        output_refs={"candidate_id": 7},
        failure_class=None,
    )

    actions = plan_resume_actions(run_id="run-1", db=store.db)

    assert actions == [
        ResumeAction(
            action="schedule_review",
            task_id="task_001",
            candidate_id=7,
            writes=True,
            reason="implement_completed_review_not_started",
        )
    ]
    assert [activity["activity_type"] for activity in store.db.list_activities("run-1")] == ["implement"]


def test_resume_executor_stops_at_human_decision(tmp_path: Path) -> None:
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
        output_refs={"candidate_id": 7},
        failure_class="needs_plan_fix",
    )
    store.create_decision_packet(
        run_id="run-1",
        decision_id="task_001.review.001.decision",
        task_id="task_001",
        failure_class="needs_plan_fix",
        summary="fix plan",
        payload={"candidate_id": 7},
    )

    result = ResumeExecutor(db=store.db, run_id="run-1").execute(
        actions=plan_resume_actions(run_id="run-1", db=store.db)
    )

    assert result["executed"] == []
    assert result["blocked"]["decision_id"] == "task_001.review.001.decision"


def test_resume_executor_records_automatic_action_event(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = ResumeAction(
        action="schedule_merge",
        task_id="task_001",
        candidate_id=7,
        writes=True,
        reason="verification_passed_merge_not_started",
    )

    result = ResumeExecutor(
        db=store.db,
        run_id="run-1",
        handlers={"schedule_merge": lambda action: {"candidate_id": action.candidate_id, "merged": True}},
    ).execute(actions=[action])
    events = store.db.list_workflow_events("run-1")

    assert result["executed"] == [{**action.__dict__, "result": {"candidate_id": 7, "merged": True}}]
    assert events[-1]["event_type"] == "ResumeActionExecuted"
    assert events[-1]["payload"]["action"] == "schedule_merge"
    assert events[-1]["payload"]["result"]["merged"] is True


def test_resume_executor_blocks_write_action_without_handler(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = ResumeAction(
        action="schedule_review",
        task_id="task_001",
        candidate_id=7,
        writes=True,
        reason="implement_completed_review_not_started",
    )

    result = ResumeExecutor(db=store.db, run_id="run-1").execute(actions=[action])

    assert result["executed"] == []
    assert result["blocked"]["reason"] == "missing_resume_handler"
    assert result["blocked"]["action"] == "schedule_review"
    assert store.db.list_workflow_events("run-1") == []


def test_resume_executor_reconstructs_missing_checkpoint_from_merge_activity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.db.upsert_task(
        TaskSpec(
            task_id="task_001",
            title="Task",
            risk="low",
            phase="implementation",
            dependencies=(),
            spec_refs=(),
            file_claims=(),
            acceptance_commands=("pytest",),
        )
    )
    store.create_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-000",
        commit_sha="base",
        parent_checkpoint_id=None,
        merged_candidate_id=None,
        reason="initial",
    )
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.merge.007",
        idempotency_key="run-1:task_001:merge:007",
        task_id="task_001",
        activity_type="merge",
        input_refs={"candidate_id": 7},
    )
    store.complete_activity(
        activity_id="task_001.merge.007",
        status=ActivityStatus.COMPLETED,
        output_refs={"checkpoint_id": "cp-001", "commit_sha": "merged"},
        failure_class=None,
    )

    action = ResumeAction(
        action="verify_checkpoint",
        task_id="task_001",
        candidate_id=7,
        writes=True,
        reason="merge_completed_checkpoint_should_exist",
    )
    result = ResumeExecutor(db=store.db, run_id="run-1").execute(actions=[action])

    checkpoint = store.db.get_checkpoint("cp-001")
    assert checkpoint["reason"] == "merged:task_001"
    assert checkpoint["commit_sha"] == "merged"
    assert checkpoint["parent_checkpoint_id"] == "cp-000"
    assert result["executed"][0]["result"]["checkpoint_id"] == "cp-001"
    assert result["executed"][0]["result"]["reconstructed"] is True
