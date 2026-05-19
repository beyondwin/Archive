#!/usr/bin/env python3
"""Inspect active or stale kws-cpe runs without mutating them."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


FINISHED_OUTCOMES = {"finished", "blocked", "failed", "cancelled"}


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def redacted(path_text: object, codex_home: Path) -> str:
    if not isinstance(path_text, str) or not path_text:
        return ""
    path = Path(path_text).expanduser()
    try:
        rel = path.resolve(strict=False).relative_to(codex_home.resolve(strict=False))
    except ValueError:
        return str(path)
    return str(Path("~/.codex") / rel)


def mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_state(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def plan_matches(state_plan: object, requested_plan: str) -> bool:
    if not isinstance(state_plan, str):
        return False
    if state_plan == requested_plan:
        return True
    return Path(state_plan).as_posix() == Path(requested_plan).as_posix()


def inspect_runs(codex_home: Path, plan: str, include_finished: bool) -> dict:
    orchestrator = codex_home / "orchestrator"
    records: list[dict] = []
    if orchestrator.is_dir():
        for state_path in sorted(orchestrator.glob("*/state.json")):
            state = load_state(state_path)
            if not state or not plan_matches(state.get("plan"), plan):
                continue
            outcome = state.get("lifecycle_outcome")
            if outcome in FINISHED_OUTCOMES and not include_finished:
                continue
            worktree = Path(str(state.get("worktree") or ""))
            missing_worktree = not worktree.exists()
            records.append(
                {
                    "run_id": state.get("run_id") or state_path.parent.name,
                    "state_path": redacted(str(state_path), codex_home),
                    "worktree": redacted(str(worktree), codex_home),
                    "current_task": state.get("current_task"),
                    "lifecycle_outcome": outcome,
                    "missing_worktree": missing_worktree,
                    "orphaned_worktree": False,
                    "state_mtime": mtime_iso(state_path),
                }
            )
    return {
        "schema_version": "1",
        "plan": plan,
        "active_runs": records,
        "ambiguous": len(records) > 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output")
    parser.add_argument("--include-finished", action="store_true")
    args = parser.parse_args()

    codex_home = Path(args.codex_home).expanduser().resolve()
    report = inspect_runs(codex_home, args.plan, args.include_finished)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(output)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
