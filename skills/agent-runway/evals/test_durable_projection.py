from __future__ import annotations

from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.durable_projection import read_durable_projection
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.workflow_store import ActivityStatus, WorkflowStore


def _task(task_id: str, *, deps: tuple[str, ...] = ()) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title=task_id,
        risk="low",
        phase="implementation",
        dependencies=deps,
        spec_refs=("S1.1",),
        file_claims=(FileClaim(f"src/{task_id}.py", "owned"),),
        acceptance_commands=("python -m pytest",),
    )


def _db(tmp_path: Path) -> AgentRunwayDb:
    return AgentRunwayDb.open(tmp_path / "state.sqlite")


def test_projection_repairs_merged_task_without_checkpoint_instead_of_releasing_dependent(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_task(_task("task_001"))
    db.upsert_task(_task("task_002", deps=("task_001",)))
    db.set_task_status("task_001", "merged")

    projection = read_durable_projection(run_id="run-1", db=db)

    assert projection.completed_checkpoint_tasks == []
    assert projection.checkpoint_repair_tasks == ["task_001"]
    assert [task["task_id"] for task in projection.ready_tasks] == []
    assert projection.next_automatic_action == "verify_checkpoint"


def test_projection_marks_dependent_ready_after_dependency_checkpoint(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    db.upsert_task(_task("task_002", deps=("task_001",)))
    db.set_task_status("task_001", "merged")
    store.create_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-001",
        commit_sha="abc123",
        parent_checkpoint_id=None,
        merged_candidate_id=1,
        reason="merged:task_001",
    )

    projection = read_durable_projection(run_id="run-1", db=db)

    assert projection.completed_checkpoint_tasks == ["task_001"]
    assert [task["task_id"] for task in projection.ready_tasks] == ["task_002"]
    assert projection.latest_checkpoint == {
        "checkpoint_id": "cp-001",
        "commit_sha": "abc123",
        "reason": "merged:task_001",
    }


def test_projection_surfaces_human_decision_packet(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
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
        summary="review requires plan correction",
        payload={"candidate_id": 7},
    )

    projection = read_durable_projection(run_id="run-1", db=db)

    assert projection.blocked_node == "task_001.review.001"
    assert projection.failure_class == "needs_plan_fix"
    assert projection.next_automatic_action is None
    assert projection.required_human_decision == "fix plan"
    assert projection.decision_packet["decision_id"] == "task_001.review.001.decision"
