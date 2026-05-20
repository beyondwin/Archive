from __future__ import annotations

import json
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.diagnostics import diagnose_run
from agentrunway.models import FileClaim, TaskSpec


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Example",
        risk="medium",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim(path="src/example.py", mode="owned"),),
        acceptance_commands=("python -m pytest",),
    )


def _run_json(run_dir: Path, status: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": "run_001",
        "status": status,
        "run_dir": str(run_dir),
        "state_db": str(run_dir / "state.sqlite"),
        "tasks": [],
    }
    payload.update(extra)
    (run_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_finished_run_is_healthy(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    run_json = _run_json(run_dir, "finished")

    diagnosis = diagnose_run(run_json=run_json, db=db)

    assert diagnosis.status == "finished"
    assert diagnosis.reason == "none"
    assert diagnosis.next_action == "apply or inspect artifacts"


def test_blocked_task_reports_blocked_by_gate(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.set_task_status("task_001", "blocked")
    run_json = _run_json(run_dir, "blocked")

    diagnosis = diagnose_run(run_json=run_json, db=db)

    assert diagnosis.status == "blocked_by_gate"
    assert diagnosis.reason == "gate_budget_exhausted"
    assert diagnosis.blocked_tasks == ["task_001"]


def test_dead_worker_missing_result_needs_resume(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(tmp_path / "worker"),
        branch="worker",
        state="running",
        handle_json={"pid": 999999},
    )
    run_json = _run_json(run_dir, "running")

    diagnosis = diagnose_run(run_json=run_json, db=db)

    assert diagnosis.status == "needs_resume"
    assert diagnosis.reason == "dead_worker_missing_result"
    assert "resume" in diagnosis.safe_actions


def test_merge_conflict_reports_conflict_redispatch(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=("abc123",),
        changed_files=("src/example.py",),
        status="merge_conflict",
    )
    run_json = _run_json(run_dir, "blocked")

    diagnosis = diagnose_run(run_json=run_json, db=db)

    assert diagnosis.status == "needs_conflict_redispatch"
    assert diagnosis.reason == "merge_conflict"
    assert diagnosis.conflict == {"task_id": "task_001", "candidate_id": 1}
