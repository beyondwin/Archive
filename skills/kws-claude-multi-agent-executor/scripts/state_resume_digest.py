#!/usr/bin/env python3
"""Emit a compact resume digest from state.json (v2.29 — I10).

A resumed orchestrator session previously loaded the entire state.json into
context to find out where it was. This helper returns only the live counters and
pointers needed to boot — the resumed session re-reads specific `<active>` paths
just-in-time for whatever it actually needs next (Anthropic / LangGraph
file-based-memory principle: reconstruct from the file, not the history).

The digest is a convenience READ. The authority remains state.json, and every
WRITE still goes through state_set.py / phase_boundary.py.

usage:  state_resume_digest.py <state.json>
stdout: one compact JSON object (counters + pointers only — no raw task bodies).
exit:   0 ok / 2 state file not found / 1 parse error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _active(state: dict) -> dict:
    if state.get("plan_chain"):
        idx = state.get("active_plan", 0)
        chain = state["plan_chain"]
        if isinstance(idx, int) and 0 <= idx < len(chain):
            return chain[idx]
        return chain[0] if chain else {}
    return state


def build_digest(state: dict) -> dict:
    active = _active(state)
    tasks = active.get("tasks") or {}
    done = sum(1 for t in tasks.values() if (t or {}).get("status") == "COMPLETE")
    skipped = sum(1 for t in tasks.values() if (t or {}).get("status") == "SKIPPED")
    return {
        "mode": state.get("mode"),
        "active_plan": state.get("active_plan"),
        "current_task": state.get("current_task"),
        "current_step_within_task": state.get("current_step_within_task"),
        "last_completed_task": active.get("last_completed_task"),
        "tasks_total": len(tasks),
        "tasks_done": done,
        "tasks_skipped": skipped,
        "pending_verification": list(active.get("low_tasks_pending_verification") or []),
        "worktree": state.get("worktree"),
        "orchestrator_dir": state.get("orchestrator_dir"),
        "test_command": state.get("test_command"),
        "gaps": {
            "verification": len(active.get("verification_gaps") or []),
            "docs": len(active.get("docs_gaps") or []),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("state_path", help="path to <orch_dir>/state.json")
    args = ap.parse_args(argv)

    path = Path(args.state_path)
    if not path.is_file():
        print(f"error: state file not found: {path}", file=sys.stderr)
        return 2
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: state JSON parse failed: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(json.dumps(build_digest(state), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
