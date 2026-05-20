from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

from agentrunway.retention import clean_retention, parse_retention_window, plan_retention_clean


def _touch_old(path: Path) -> None:
    old = path.stat().st_mtime - timedelta(days=30).total_seconds()
    os.utime(path, (old, old))


def _write_run(run_dir: Path, status: str) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "state.sqlite").write_text("", encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": run_dir.name, "status": status, "run_dir": str(run_dir)}),
        encoding="utf-8",
    )
    _touch_old(run_dir)


def test_parse_retention_window_days() -> None:
    assert parse_retention_window("14d") == timedelta(days=14)


def test_retention_planner_keeps_running_runs_and_finds_orphan_worktrees(tmp_path: Path) -> None:
    home = tmp_path / "home"
    old_finished = home / "runs" / "ws" / "old-finished"
    running = home / "runs" / "ws" / "running"
    orphan_worktree = home / "worktrees" / "ws" / "orphan"
    _write_run(old_finished, "finished")
    _write_run(running, "running")
    (running / ".agentrunway-detached").mkdir()
    (running / ".agentrunway-detached" / "pidfile").write_text("123\n", encoding="utf-8")
    orphan_worktree.mkdir(parents=True)
    _touch_old(orphan_worktree)

    plan = plan_retention_clean(home, older_than="14d", successful=True)

    removable = {(item["kind"], item["path"]) for item in plan["candidates"]}
    blocked = {(item["kind"], item["path"], item["reason"]) for item in plan["blocked"]}
    assert ("run", str(old_finished)) in removable
    assert ("worktree", str(orphan_worktree)) in removable
    assert ("run", str(running), "active_run") in blocked


def test_clean_retention_dry_run_does_not_delete_and_non_dry_run_removes_candidates(tmp_path: Path) -> None:
    home = tmp_path / "home"
    old_finished = home / "runs" / "ws" / "old-finished"
    orphan_worktree = home / "worktrees" / "ws" / "orphan"
    _write_run(old_finished, "finished")
    orphan_worktree.mkdir(parents=True)
    _touch_old(orphan_worktree)

    dry = clean_retention(home, older_than="14d", successful=True, dry_run=True)
    assert dry["removed"] == 0
    assert old_finished.exists()
    assert orphan_worktree.exists()

    applied = clean_retention(home, older_than="14d", successful=True, dry_run=False)
    assert applied["removed"] == 2
    assert not old_finished.exists()
    assert not orphan_worktree.exists()
