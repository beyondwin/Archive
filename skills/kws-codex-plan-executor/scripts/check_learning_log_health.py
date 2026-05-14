#!/usr/bin/env python3
"""Summarize kws-codex-plan-executor learning-log health."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_LOG_ROOT = Path("~/.codex/learning/kws-codex-plan-executor").expanduser()
TERMINAL_OUTCOMES = {"success", "blocked", "error"}


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
    warnings: list[str] = []

    status = "unknown"
    if final and final.get("outcome"):
        status = str(final["outcome"])
        if index_row.get("outcome") != status:
            warnings.append("index_outcome_stale")
    elif meta.get("outcome") in TERMINAL_OUTCOMES:
        status = str(meta["outcome"])
    elif index_row.get("outcome") in TERMINAL_OUTCOMES:
        status = str(index_row["outcome"])
    elif meta:
        started_at = parse_time(str(meta.get("started_at") or ""))
        ended_at = meta.get("ended_at")
        pid_alive = pid_is_alive(meta.get("pid"))
        old_enough = started_at is not None and now - started_at > dt.timedelta(minutes=stale_after_minutes)
        if ended_at is None and pid_alive is False and old_enough:
            status = "stale"
            warnings.append("dead_pid_unclosed")

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
        "warnings": warnings,
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
