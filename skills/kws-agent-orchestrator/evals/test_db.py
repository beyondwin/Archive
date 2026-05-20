from __future__ import annotations

from pathlib import Path

from kao.db import KaoDb
from kao.models import TaskSpec


def test_db_initializes_required_tables(tmp_path: Path) -> None:
    db = KaoDb.open(tmp_path / "state.sqlite")
    tables = db.table_names()
    for table in (
        "runs",
        "tasks",
        "task_packets",
        "file_claims",
        "waves",
        "workers",
        "messages",
        "artifacts",
        "merge_queue",
        "agentlens_events",
        "cost_ledger",
        "method_audits",
        "context_snapshots",
        "worktree_registry",
        "resource_locks",
        "watchdog_events",
    ):
        assert table in tables


def test_create_run_and_task_round_trip(tmp_path: Path) -> None:
    db = KaoDb.open(tmp_path / "state.sqlite")
    db.create_run(
        run_id="run-1",
        workspace_id="repo-abc123",
        repo_root="/repo",
        plan_path="plan.md",
        spec_path="spec.md",
        plan_hash="sha256:1",
        spec_hash="sha256:2",
        base_commit_sha="abc",
        model_profile="codex-default",
    )
    task = TaskSpec(
        task_id="task_001",
        title="Add parser",
        risk="medium",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(),
        acceptance_commands=("pytest",),
    )
    db.upsert_task(task)
    assert db.get_run("run-1")["status"] == "created"
    assert db.get_task("task_001")["title"] == "Add parser"
