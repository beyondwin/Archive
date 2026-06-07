#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update CPE progress ledger for a task.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--progress-made", action="store_true")
    parser.add_argument("--goal-satisfied", action="store_true")
    parser.add_argument("--root-signature")
    parser.add_argument("--next-action", required=True)
    args = parser.parse_args()
    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    ledger = state.setdefault("progress_ledger", {})
    entry = ledger.setdefault(
        args.task_id,
        {
            "goal_satisfied": False,
            "progress_made": False,
            "stall_count": 0,
            "last_progress_at": None,
            "next_action": "",
            "needs_operator": False,
        },
    )
    entry["goal_satisfied"] = bool(args.goal_satisfied)
    entry["progress_made"] = bool(args.progress_made)
    if args.progress_made:
        entry["stall_count"] = 0
        entry["last_progress_at"] = now_iso()
        entry.pop("last_root_signature", None)
    elif args.root_signature:
        if entry.get("last_root_signature") == args.root_signature:
            entry["stall_count"] = int(entry.get("stall_count", 0)) + 1
        else:
            entry["stall_count"] = 1
            entry["last_root_signature"] = args.root_signature
    entry["next_action"] = args.next_action
    entry["needs_operator"] = int(entry.get("stall_count", 0)) >= 2
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(state_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
