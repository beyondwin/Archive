#!/usr/bin/env python3
"""Summarize kws-codex-plan-executor learning-log health."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_LOG_ROOT = Path("~/.codex/learning/kws-codex-plan-executor").expanduser()
TERMINAL_OUTCOMES = {"success", "blocked", "error"}
STATE_TERMINAL_OUTCOMES = {"blocked", "failed", "userinterlude", "askuserQuestion"}


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be an object")
    return data


def read_index(log_root: Path) -> list[dict[str, Any]]:
    path = log_root / "index.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def run_dir_for(log_root: Path, run_id: str) -> Path:
    date = f"{run_id[0:4]}-{run_id[4:6]}-{run_id[6:8]}"
    return log_root / "runs" / date / run_id


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed


def pid_is_alive(pid: Any) -> bool | None:
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def helper_pid(meta: dict[str, Any]) -> Any:
    value = meta.get("helper_pid")
    return value if isinstance(value, int) else meta.get("pid")


def resolve_worktree_path(meta: dict[str, Any]) -> Path | None:
    value = meta.get("worktree_path")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def resolve_project_state_path(meta: dict[str, Any]) -> Path | None:
    worktree = resolve_worktree_path(meta)
    state_path = meta.get("state_path")
    if worktree is None or not isinstance(state_path, str) or not state_path.strip():
        return None
    candidate = Path(state_path).expanduser()
    if candidate.is_absolute():
        return candidate
    return worktree / candidate


def read_project_state(meta: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None, list[str]]:
    diagnostics: list[str] = []
    worktree = resolve_worktree_path(meta)
    if worktree is None:
        diagnostics.append("missing_worktree_path")
        return None, None, diagnostics
    if not worktree.exists():
        diagnostics.append("missing_worktree")

    state_path = resolve_project_state_path(meta)
    if state_path is None:
        diagnostics.append("missing_state_path")
        return None, None, diagnostics

    state = read_json(state_path)
    if state is None:
        diagnostics.append("missing_project_state")
        return state_path, None, diagnostics
    return state_path, state, diagnostics


def task_counts(state: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return counts
    for task in tasks.values():
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def summarize_project_state(state_path: Path, state: dict[str, Any]) -> dict[str, Any]:
    health = state.get("context_health") if isinstance(state.get("context_health"), dict) else {}
    return {
        "state_path": str(state_path),
        "current_task": state.get("current_task"),
        "current_phase": state.get("current_phase"),
        "lifecycle_outcome": state.get("lifecycle_outcome"),
        "context_health_status": health.get("status"),
        "context_health_last_checked_at": health.get("last_checked_at"),
        "next_action": health.get("next_action"),
        "task_counts": task_counts(state),
        "timestamps": state.get("timestamps") if isinstance(state.get("timestamps"), dict) else {},
    }


def stale_warning_from_state_age(
    state: dict[str, Any],
    *,
    now: dt.datetime,
    stale_after_minutes: int,
) -> str | None:
    timestamps = state.get("timestamps") if isinstance(state.get("timestamps"), dict) else {}
    updated_at = parse_time(timestamps.get("updated_at") if isinstance(timestamps.get("updated_at"), str) else None)
    if updated_at is None:
        return None
    if now - updated_at > dt.timedelta(minutes=stale_after_minutes):
        return "project_state_inactive_past_threshold"
    return None


def classify_from_project_state(
    state: dict[str, Any],
    *,
    now: dt.datetime,
    stale_after_minutes: int,
) -> tuple[str, list[str]]:
    outcome = state.get("lifecycle_outcome")
    if outcome == "finished":
        return "needs_finalization", []
    if outcome in STATE_TERMINAL_OUTCOMES:
        return str(outcome), []

    counts = task_counts(state)
    if counts.get("in_progress", 0) > 0:
        return "in_progress", []

    pending = counts.get("pending", 0)
    completed = counts.get("completed", 0)
    current_phase = state.get("current_phase")
    if current_phase in {"final_verification", "finish", "completion"}:
        return "needs_finalization", []
    if completed > 0 and pending == 0:
        return "needs_finalization", []
    if current_phase == "task_loop" and pending > 0 and completed > 0:
        return "in_progress", []
    if current_phase == "task_loop" and pending > 0:
        stale_warning = stale_warning_from_state_age(state, now=now, stale_after_minutes=stale_after_minutes)
        if stale_warning:
            return "stale_candidate", [stale_warning]
        return "in_progress", []

    stale_warning = stale_warning_from_state_age(state, now=now, stale_after_minutes=stale_after_minutes)
    if stale_warning:
        return "stale_candidate", [stale_warning]
    return "unknown", []


def summarize_git_state(worktree: Path | None) -> dict[str, Any] | None:
    if worktree is None:
        return None
    if not worktree.exists():
        return {"worktree_exists": False}

    try:
        status = subprocess.run(
            ["git", "-C", str(worktree), "status", "--short", "--untracked-files=all"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
        head = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--short", "HEAD"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
        branch = subprocess.run(
            ["git", "-C", str(worktree), "branch", "--show-current"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"worktree_exists": True, "git_readable": False}

    if status.returncode != 0:
        return {"worktree_exists": True, "git_readable": False}

    lines = [line for line in status.stdout.splitlines() if line.strip()]
    return {
        "worktree_exists": True,
        "git_readable": True,
        "short_status_count": len(lines),
        "modified_count": sum(1 for line in lines if "M" in line[:2]),
        "deleted_count": sum(1 for line in lines if "D" in line[:2]),
        "staged_count": sum(1 for line in lines if line[:1] not in {" ", "?"}),
        "untracked_count": sum(1 for line in lines if line.startswith("??")),
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
    }


def count_events(run_dir: Path) -> int:
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def summarize_run(
    log_root: Path,
    index_row: dict[str, Any],
    *,
    now: dt.datetime,
    stale_after_minutes: int,
) -> dict[str, Any]:
    run_id = str(index_row["run_id"])
    run_dir = run_dir_for(log_root, run_id)
    meta = read_json(run_dir / "meta.json") or {}
    final = read_json(run_dir / "final.json")
    event_count = count_events(run_dir)
    diagnostics: dict[str, list[str]] = {"info": [], "warnings": []}
    project_state_summary: dict[str, Any] | None = None
    git_state: dict[str, Any] | None = None

    def add_diagnostic(kind: str, code: str) -> None:
        target = diagnostics[kind]
        if code not in target:
            target.append(code)

    status = "unknown"
    if final and final.get("outcome"):
        status = str(final["outcome"])
        if index_row.get("outcome") != status:
            add_diagnostic("info", "index_outcome_stale")
        git_state = summarize_git_state(resolve_worktree_path(meta)) if meta else None
    elif meta:
        pid_alive = pid_is_alive(helper_pid(meta))
        if pid_alive is False:
            add_diagnostic("info", "helper_pid_dead")

        git_state = summarize_git_state(resolve_worktree_path(meta))
        project_state_path, project_state, project_state_diagnostics = read_project_state(meta)
        for code in project_state_diagnostics:
            add_diagnostic("warnings", code)
        if project_state_path is not None and project_state is not None:
            project_state_summary = summarize_project_state(project_state_path, project_state)
            status, state_warnings = classify_from_project_state(
                project_state,
                now=now,
                stale_after_minutes=stale_after_minutes,
            )
            add_diagnostic("info", "missing_learning_final")
            for code in state_warnings:
                add_diagnostic("warnings", code)
        elif meta.get("outcome") in TERMINAL_OUTCOMES:
            status = str(meta["outcome"])
        elif index_row.get("outcome") in TERMINAL_OUTCOMES:
            status = str(index_row["outcome"])
    elif index_row.get("outcome") in TERMINAL_OUTCOMES:
        status = str(index_row["outcome"])

    if (
        status in {"in_progress", "needs_finalization"}
        and isinstance(git_state, dict)
        and git_state.get("short_status_count", 0) > 0
    ):
        add_diagnostic("warnings", "dirty_worktree_during_in_progress")

    event_note = "routine_success_no_notable_events" if status == "success" and event_count == 0 else None
    source = meta or index_row
    terminal = final or meta
    return {
        "run_id": run_id,
        "status": status,
        "repo": source.get("repo"),
        "plan_path": source.get("plan_path"),
        "started_at": source.get("started_at"),
        "ended_at": terminal.get("ended_at") if terminal else None,
        "event_count": event_count,
        "event_note": event_note,
        "diagnostics": diagnostics,
        "warnings": diagnostics["warnings"],
        "project_state": project_state_summary,
        "git_state": git_state,
        "run_dir": str(run_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-root", default=str(DEFAULT_LOG_ROOT))
    parser.add_argument("--latest", type=int, default=5)
    parser.add_argument("--stale-after-minutes", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    log_root = Path(args.log_root).expanduser()
    now = dt.datetime.now(dt.UTC)
    rows = read_index(log_root)[-args.latest :]
    summaries = [
        summarize_run(log_root, row, now=now, stale_after_minutes=args.stale_after_minutes)
        for row in rows
    ]

    if args.json:
        print(json.dumps({"schema_version": "1", "runs": summaries}, indent=2, sort_keys=True))
        return 0

    for item in summaries:
        warnings = ",".join(item["warnings"]) if item["warnings"] else "-"
        print(f"{item['status']:8} events={item['event_count']} warnings={warnings} {item['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
