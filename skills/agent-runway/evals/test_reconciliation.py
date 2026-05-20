from __future__ import annotations

import json
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.reconciliation import apply_reconciliation_plan, plan_reconciliation


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Example",
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim(path="src/example.py", mode="owned"),),
        acceptance_commands=("python -m pytest",),
    )


def test_plan_reconciliation_reconciles_valid_result_artifact_forward(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(tmp_path / "worker"),
        branch="agentrunway/run/task_001-implementer-001",
        state="running",
        handle_json={},
    )
    result_path = run_dir / "artifacts" / "task_001" / "task_001-implementer-001" / "worker_result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(
            {
                "schema": "agentrunway.worker_result.v1",
                "worker_id": "task_001-implementer-001",
                "task_id": "task_001",
                "role": "implementer",
                "status": "success",
                "changed_files": [],
                "summary": "ok",
                "method_audit": {},
            }
        ),
        encoding="utf-8",
    )

    plan = plan_reconciliation(run_id="run-1", run_dir=run_dir, db=db)

    assert plan["actions"] == [
        {
            "target": "task_001-implementer-001",
            "action": "reconcile_forward",
            "reason": "valid_result_artifact_exists",
            "writes": True,
        }
    ]


def test_plan_reconciliation_retries_dead_worker_missing_result(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(tmp_path / "worker"),
        branch="agentrunway/run/task_001-implementer-001",
        state="running",
        handle_json={"pid": 999999},
    )

    plan = plan_reconciliation(run_id="run-1", run_dir=run_dir, db=db)

    assert plan["actions"][0]["action"] == "retry"
    assert plan["actions"][0]["reason"] == "dead_process_missing_result"


def test_apply_reconciliation_plan_is_idempotent_for_reconcile_forward(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(tmp_path / "worker"),
        branch="agentrunway/run/task_001-implementer-001",
        state="running",
        handle_json={},
    )
    plan = {
        "run_id": "run-1",
        "actions": [
            {
                "target": "task_001-implementer-001",
                "action": "reconcile_forward",
                "reason": "valid_result_artifact_exists",
                "writes": True,
            }
        ],
    }

    apply_reconciliation_plan(db=db, plan=plan)
    apply_reconciliation_plan(db=db, plan=plan)

    assert db.get_worker("task_001-implementer-001")["state"] == "result_collected"
    events = [row for row in db.list_events() if row["event_type"] == "agentrunway.resume_action"]
    assert len(events) == 1


def test_plan_reconciliation_detects_interrupted_cherry_pick(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    main_worktree = tmp_path / "main"
    git_dir = main_worktree / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "CHERRY_PICK_HEAD").write_text("abc123\n", encoding="utf-8")
    (run_dir / "run.json").parent.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-1", "main_worktree": str(main_worktree)}),
        encoding="utf-8",
    )
    db = AgentRunwayDb.open(run_dir / "state.sqlite")

    plan = plan_reconciliation(run_id="run-1", run_dir=run_dir, db=db)

    assert plan["actions"][0] == {
        "target": str(main_worktree),
        "action": "abort_cherry_pick",
        "reason": "interrupted_cherry_pick",
        "writes": True,
    }


def test_plan_reconciliation_ignores_empty_main_worktree_string(tmp_path: Path, monkeypatch) -> None:
    cwd = tmp_path / "cwd"
    (cwd / ".git").mkdir(parents=True)
    (cwd / ".git" / "CHERRY_PICK_HEAD").write_text("abc123\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({"run_id": "run-1", "main_worktree": ""}), encoding="utf-8")
    db = AgentRunwayDb.open(run_dir / "state.sqlite")

    plan = plan_reconciliation(run_id="run-1", run_dir=run_dir, db=db)

    assert plan["actions"] == []


def test_plan_reconciliation_blocks_after_retry_budget(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    for attempt, state in ((1, "stalled"), (2, "running")):
        db.create_worker_attempt(
            worker_id=f"task_001-implementer-{attempt:03d}",
            task_id="task_001",
            role="implementer",
            runtime="codex",
            model="gpt-5.5",
            reasoning_effort="high",
            attempt=attempt,
            worktree_path=str(tmp_path / f"worker-{attempt}"),
            branch=f"agentrunway/run/task_001-implementer-{attempt:03d}",
            state=state,
            handle_json={"pid": 999999},
        )

    plan = plan_reconciliation(run_id="run-1", run_dir=run_dir, db=db)

    assert plan["actions"] == [
        {
            "target": "task_001",
            "action": "block",
            "reason": "retry_budget_exhausted",
            "writes": True,
        }
    ]
