from __future__ import annotations

from pathlib import Path

from agentrunway.checkpoint_scheduler import CheckpointScheduler
from agentrunway.db import AgentRunwayDb
from agentrunway.durable_projection import read_durable_projection
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.workflow_store import WorkflowStore


def _task(
    task_id: str,
    *,
    deps: tuple[str, ...] = (),
    claims: tuple[FileClaim, ...] = (),
    resources: tuple[str, ...] = (),
    risk: str = "low",
    serial: bool = False,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title=task_id,
        risk=risk,  # type: ignore[arg-type]
        phase="implementation",
        dependencies=deps,
        spec_refs=("S1.1",),
        file_claims=claims or (FileClaim(f"src/{task_id}.py", "owned"),),
        acceptance_commands=("python -m pytest",),
        resource_keys=resources,
        serial=serial,
    )


def _db(tmp_path: Path) -> AgentRunwayDb:
    return AgentRunwayDb.open(tmp_path / "state.sqlite")


def test_scheduler_returns_safe_wave_from_projection(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_task(_task("task_001", claims=(FileClaim("src/a.py", "owned"),)))
    db.upsert_task(_task("task_002", claims=(FileClaim("src/b.py", "owned"),)))
    projection = read_durable_projection(run_id="run-1", db=db)

    wave = CheckpointScheduler().next_wave(projection=projection)

    assert [task["task_id"] for task in wave] == ["task_001", "task_002"]


def test_scheduler_serializes_conflicting_ready_tasks(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.upsert_task(_task("task_001", claims=(FileClaim("src/shared.py", "owned"),)))
    db.upsert_task(_task("task_002", claims=(FileClaim("src/shared.py", "owned"),)))
    projection = read_durable_projection(run_id="run-1", db=db)

    wave = CheckpointScheduler().next_wave(projection=projection)

    assert [task["task_id"] for task in wave] == ["task_001"]


def test_scheduler_waits_for_checkpoint_before_dependency_release(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store = WorkflowStore(db)
    db.upsert_task(_task("task_001"))
    db.upsert_task(_task("task_002", deps=("task_001",)))
    db.set_task_status("task_001", "merged")
    projection_before = read_durable_projection(run_id="run-1", db=db)

    store.create_checkpoint(
        run_id="run-1",
        checkpoint_id="cp-001",
        commit_sha="abc123",
        parent_checkpoint_id=None,
        merged_candidate_id=1,
        reason="merged:task_001",
    )
    projection_after = read_durable_projection(run_id="run-1", db=db)

    assert CheckpointScheduler().next_wave(projection=projection_before) == []
    assert projection_before.checkpoint_repair_tasks == ["task_001"]
    assert projection_before.next_automatic_action == "verify_checkpoint"
    assert [task["task_id"] for task in CheckpointScheduler().next_wave(projection=projection_after)] == ["task_002"]
