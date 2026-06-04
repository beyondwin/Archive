#!/usr/bin/env python3
"""Finalization-consistency gate for a kws-claude-multi-agent-executor run.

Checks that a run that claims to be finished is actually finalized:
completed_at stamped, no LOW task left PENDING_BATCH, cost ledger populated,
per-task timing present. `--fix` performs only the one genuinely-safe write
(stamp completed_at); everything else is a loud report, never a silent mutation.

Exit 0: no unfixable FAIL (WARNs allowed).
Exit 1: at least one FAIL (after --fix, if used).
Exit 2: validator could not parse state.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _active_trees(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    chain = state.get("plan_chain")
    if isinstance(chain, list):
        return [(f"plan_chain[{i}]", entry) for i, entry in enumerate(chain)]
    return [("state", state)]


def evaluate(state: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []

    def add(level: str, scope: str, code: str, detail: str, fixable: bool = False) -> None:
        findings.append({"level": level, "scope": scope, "code": code,
                         "detail": detail, "fixable": fixable})

    # Run-level: completed_at.
    completed_at = (state.get("timestamps") or {}).get("completed_at")
    if not completed_at:
        add("FAIL", "state", "completed_at_null",
            "timestamps.completed_at is null/absent", fixable=True)

    # Run-level: cost ledger dispatches.
    if not state.get("cost_tracking_waived"):
        dispatches = ((state.get("cost_ledger") or {}).get("totals") or {}).get("dispatches", 0)
        if not dispatches:
            add("WARN", "state", "cost_dispatches_zero",
                "cost_ledger.totals.dispatches == 0 (accumulate_cost.py never ran)")

    # Per-tree task checks.
    for scope, tree in _active_trees(state):
        tasks = tree.get("tasks")
        tasks = tasks if isinstance(tasks, dict) else {}
        for task_id, task in tasks.items():
            status = task.get("status")
            if status not in ("COMPLETE", "SKIPPED"):
                add("FAIL", scope, "task_not_terminal",
                    f"{task_id}: status={status!r} (expected COMPLETE/SKIPPED)")
            if task.get("verifier") == "PENDING_BATCH":
                add("FAIL", scope, "verifier_pending_batch",
                    f"{task_id}: verifier still PENDING_BATCH (final LOW sweep never wrote back)")
            timing = task.get("timing") or {}
            if not timing.get("started"):
                add("WARN", scope, "timing_started_missing",
                    f"{task_id}: timing.started absent (per-task duration uncomputable)")

    # Run-level consistency: a COMPLETE run must be fully finalized.
    if state.get("status") == "COMPLETE":
        if any(f["code"] in ("completed_at_null", "verifier_pending_batch") for f in findings):
            add("FAIL", "state", "complete_but_unfinalized",
                "status==COMPLETE but completed_at null or a task is PENDING_BATCH")

    unfixable_fail = any(f["level"] == "FAIL" and not f["fixable"] for f in findings)
    any_fail = any(f["level"] == "FAIL" for f in findings)
    return {"passed": not any_fail, "unfixable_fail": unfixable_fail, "findings": findings}


def apply_fix(state_path: Path) -> dict[str, Any]:
    """Stamp completed_at if null. Atomic. Returns the post-fix evaluation."""
    state = json.loads(state_path.read_text(encoding="utf-8"))
    ts = state.setdefault("timestamps", {})
    if not ts.get("completed_at"):
        ts["completed_at"] = state.get("last_completed_at") or \
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tmp = state_path.with_suffix(state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, state_path)
    return evaluate(state)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--check", action="store_true", help="report only (default)")
    ap.add_argument("--fix", action="store_true", help="stamp completed_at, then re-check")
    ap.add_argument("--active-plan", default="auto")  # accepted for contract parity
    args = ap.parse_args(argv)

    try:
        if args.fix:
            result = apply_fix(args.state)
        else:
            state = json.loads(args.state.read_text(encoding="utf-8"))
            result = evaluate(state)
    except Exception as exc:  # noqa: BLE001 — broken state is exit 2 by contract
        print(json.dumps({"passed": False, "error": f"unparseable state.json: {exc}"}))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
