from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def test_projection_ignores_resolved_blocked_activity_after_checkpoint(tmp_path: Path) -> None:
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
        output_refs={"candidate_id": 7},
        failure_class="needs_rebase",
    )
    store.create_decision_packet(
        run_id="run-1",
        decision_id="task_001.review.001.decision",
        task_id="task_001",
        failure_class="needs_rebase",
        summary="review requires rebase decision",
        payload={"candidate_id": 7},
    )
    db.set_task_status("task_001", "merged")
    store.create_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-001",
        commit_sha="abc123",
        parent_checkpoint_id=None,
        merged_candidate_id=7,
        reason="merged:task_001",
    )

    projection = read_durable_projection(run_id="run-1", db=db)

    assert projection.projection_status == "finished"
    assert projection.blocked_node is None
    assert projection.failure_class is None
    assert projection.next_automatic_action is None
    assert projection.required_human_decision is None
    assert projection.decision_packet is None


def test_projection_treats_repeated_rebase_decision_packet_as_human_decision(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.review.002",
        idempotency_key="run-1:task_001:review:002",
        task_id="task_001",
        activity_type="review",
        input_refs={"candidate_id": 8},
    )
    store.complete_activity(
        activity_id="task_001.review.002",
        status=ActivityStatus.BLOCKED,
        output_refs={"candidate_id": 8},
        failure_class="needs_rebase",
    )
    store.create_decision_packet(
        run_id="run-1",
        decision_id="task_001.review.002.decision",
        task_id="task_001",
        failure_class="needs_rebase",
        summary="review needs repeated rebase decision",
        payload={"candidate_id": 8},
    )

    projection = read_durable_projection(run_id="run-1", db=db)

    assert projection.projection_status == "blocked"
    assert projection.blocked_node == "task_001.review.002"
    assert projection.failure_class == "needs_rebase"
    assert projection.next_automatic_action is None
    assert projection.required_human_decision == "inspect decision packet"
    assert projection.decision_packet["decision_id"] == "task_001.review.002.decision"


def test_projection_blocks_dependent_when_upstream_task_is_blocked(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_task(_task("task_001"))
    db.upsert_task(_task("task_002", deps=("task_001",)))
    db.set_task_status("task_001", "blocked")

    projection = read_durable_projection(run_id="run-1", db=db)

    assert [task["task_id"] for task in projection.safe_wave] == []
    assert projection.withheld_tasks == [
        {
            "task_id": "task_002",
            "reason": "blocked_dependency",
            "blocked_dependencies": ["task_001"],
        }
    ]
    assert projection.projection_status == "blocked"


def test_projection_withholds_all_dispatch_when_human_decision_exists(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    db.upsert_task(_task("task_002"))
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
        failure_class="needs_infra_fix",
    )
    store.create_decision_packet(
        run_id="run-1",
        decision_id="task_001.review.001.decision",
        task_id="task_001",
        failure_class="needs_infra_fix",
        summary="infra fix",
        payload={"candidate_id": 7},
    )

    projection = read_durable_projection(run_id="run-1", db=db)

    assert projection.required_human_decision == "fix infrastructure"
    assert projection.safe_wave == []
    assert projection.projection_status == "blocked"


def test_projection_marks_started_activity_as_stale(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    store.start_activity(
        run_id="run-1",
        activity_id="task_001.implement.001",
        idempotency_key="run-1:task_001:implement:001",
        task_id="task_001",
        activity_type="implement",
        input_refs={},
    )
    stale_time = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(microsecond=0).isoformat()
    db.conn.execute(
        "UPDATE activities SET created_at=?, updated_at=? WHERE activity_id=?",
        (stale_time, stale_time, "task_001.implement.001"),
    )
    db.conn.commit()

    projection = read_durable_projection(run_id="run-1", db=db, stale_after_seconds=60)

    assert projection.stale_activities[0]["activity_id"] == "task_001.implement.001"
    assert projection.next_automatic_action == "classify_stale_activity"
    assert projection.safe_wave == []
    assert projection.projection_status == "blocked"
