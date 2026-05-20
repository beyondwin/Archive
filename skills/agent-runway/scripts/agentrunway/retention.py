from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def parse_retention_window(value: str) -> timedelta:
    raw = value.strip().lower()
    if raw.endswith("d"):
        return timedelta(days=int(raw[:-1] or "0"))
    if raw.endswith("h"):
        return timedelta(hours=int(raw[:-1] or "0"))
    raise ValueError(f"unsupported retention window: {value}")


def _is_old(path: Path, cutoff: datetime) -> bool:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff


def _run_status(run_dir: Path) -> str:
    run_json = run_dir / "run.json"
    if not run_json.exists():
        return "orphan"
    try:
        data = json.loads(run_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "unknown"
    return str(data.get("status") or "unknown")


def _has_detach_pidfile(run_dir: Path) -> bool:
    return (run_dir / ".agentrunway-detached" / "pidfile").exists()


def _candidate(kind: str, path: Path, reason: str) -> dict[str, str]:
    return {"kind": kind, "path": str(path), "reason": reason}


def plan_retention_clean(home: Path, *, older_than: str, successful: bool) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - parse_retention_window(older_than)
    candidates: list[dict[str, str]] = []
    blocked: list[dict[str, str]] = []
    retained: list[dict[str, str]] = []
    runs_root = home / "runs"
    worktrees_root = home / "worktrees"

    if runs_root.exists():
        for run_dir in sorted(path for path in runs_root.glob("*/*") if path.is_dir()):
            status = _run_status(run_dir)
            if status == "running" or _has_detach_pidfile(run_dir):
                blocked.append(_candidate("run", run_dir, "active_run"))
                continue
            if not _is_old(run_dir, cutoff):
                retained.append(_candidate("run", run_dir, "newer_than_retention"))
                continue
            removable_success = status in {"finished", "planning_only", "success"}
            removable_terminal = status in {"blocked", "failed", "cancelled", "orphan", "unknown"}
            if removable_success or (removable_terminal and not successful):
                reason = "successful_run_expired" if removable_success else "terminal_run_expired"
                candidates.append(_candidate("run", run_dir, reason))
            else:
                retained.append(_candidate("run", run_dir, f"status_{status}"))

    if worktrees_root.exists():
        for worktree_dir in sorted(path for path in worktrees_root.glob("*/*") if path.is_dir()):
            matching_run = runs_root / worktree_dir.parent.name / worktree_dir.name
            if matching_run.exists():
                retained.append(_candidate("worktree", worktree_dir, "matching_run_exists"))
                continue
            if _is_old(worktree_dir, cutoff):
                candidates.append(_candidate("worktree", worktree_dir, "orphan_worktree_expired"))
            else:
                retained.append(_candidate("worktree", worktree_dir, "newer_than_retention"))

    return {
        "older_than": older_than,
        "successful": successful,
        "candidates": candidates,
        "blocked": blocked,
        "retained": retained,
    }


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def clean_retention(home: Path, *, older_than: str, successful: bool, dry_run: bool) -> dict[str, Any]:
    plan = plan_retention_clean(home, older_than=older_than, successful=successful)
    removed = 0
    if not dry_run:
        for item in plan["candidates"]:
            path = Path(str(item["path"]))
            if path.exists() and _is_under(path, home):
                shutil.rmtree(path)
                removed += 1
    return {**plan, "dry_run": dry_run, "removed": removed}
