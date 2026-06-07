#!/usr/bin/env python3
"""Validate the canonical shape of a kws-claude-multi-agent-executor state.json.

Catches the non-canonical / improvised schemas observed in attached-mode runs
(e.g. empty tasks{} with per-task data in task_summaries{}, execution_order
without execution_plan, risk values outside low/mid/high).

Exit 0: canonical (no violations; warnings allowed).
Exit 1: at least one violation.
Exit 2: validator could not parse state.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

VALID_RISK = {"low", "mid", "high"}
VALID_MODES = {
    "interactive_session", "interactive_attached", "headless_pending",
    "headless_running", "headless_chained", "plan_chain_running", "plan2_running",
}
TASK_KEY_RE = re.compile(r"^task_\d+(_[a-z0-9-]+)?$")  # task_3, task_7_remediation


def _active_trees(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    chain = state.get("plan_chain")
    if isinstance(chain, list):
        return [(f"plan_chain[{i}]", entry) for i, entry in enumerate(chain)]
    return [("state", state)]


def _declared_count(tree: dict[str, Any]) -> int:
    rl = tree.get("risk_levels")
    if isinstance(rl, dict):
        return len(rl)
    eo = tree.get("execution_order")
    if isinstance(eo, list):
        return len(eo)
    return 0


def validate(state: dict[str, Any]) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def viol(scope: str, code: str, detail: str) -> None:
        violations.append({"scope": scope, "code": code, "detail": detail})

    def warn(scope: str, code: str, detail: str) -> None:
        warnings.append({"scope": scope, "code": code, "detail": detail})

    if str(state.get("schema_version")) != "2":
        warn("state", "schema_version_not_2",
             f"schema_version={state.get('schema_version')!r} (expected '2')")

    mode = state.get("mode")
    if mode not in VALID_MODES:
        viol("state", "mode_invalid", f"mode={mode!r} not in allowed enum")

    trees = _active_trees(state)
    any_tasks = any(_declared_count(t) > 0 for _, t in trees)

    if any_tasks:
        if "dispatch_config" not in state:
            viol("state", "missing_dispatch_config", "run-level dispatch_config absent")
        if "cost_ledger" not in state:
            viol("state", "missing_cost_ledger", "run-level cost_ledger absent")

    # v2.29 additive run-level field (I8). Absence is fine (default 0); present →
    # must be a non-negative int. WARN, never block — additive contract (§0.2).
    arc = state.get("auto_resolved_count")
    if arc is not None and (not isinstance(arc, int) or isinstance(arc, bool) or arc < 0):
        warn("state", "auto_resolved_count_type",
             f"auto_resolved_count={arc!r} (expected non-negative int)")

    for scope, tree in trees:
        declared = _declared_count(tree)
        tasks = tree.get("tasks")
        tasks = tasks if isinstance(tasks, dict) else {}
        summaries = tree.get("task_summaries")
        summaries = summaries if isinstance(summaries, dict) else {}

        if declared > 0 and not tasks:
            if summaries:
                viol(scope, "tasks_empty_but_declared",
                     f"{declared} tasks declared but tasks{{}} empty; "
                     f"{len(summaries)} records improvised into task_summaries")
            else:
                viol(scope, "tasks_empty_but_declared",
                     f"{declared} tasks declared but tasks{{}} empty")

        if tree.get("execution_order") is not None and tree.get("execution_plan") is None:
            viol(scope, "execution_order_without_plan",
                 "execution_order present without canonical execution_plan")

        rl = tree.get("risk_levels")
        if isinstance(rl, dict):
            for task_id, level in rl.items():
                if level not in VALID_RISK:
                    viol(scope, "risk_value_invalid",
                         f"{task_id}: risk={level!r} not in {sorted(VALID_RISK)}")

        if tasks and summaries:
            warn(scope, "task_summaries_alongside_tasks",
                 "both tasks{} and task_summaries{} populated (legacy mirror)")

        bad_keys = [k for k in tasks if not TASK_KEY_RE.match(str(k))]
        if bad_keys:
            warn(scope, "task_key_noncanonical",
                 f"non-canonical task keys: {sorted(bad_keys)} "
                 "(expected task_<N>[_<suffix>])")

        # v2.29 additive per-task fields. Absence is fine; present → typecheck (§0.2).
        for task_id, task in tasks.items():
            if not isinstance(task, dict):
                continue
            rt = task.get("retry_trace")
            if rt is not None:
                if not isinstance(rt, list):
                    warn(scope, "retry_trace_type", f"{task_id}: retry_trace not a list")
                elif any(not isinstance(e, dict) or "attempt" not in e or "kind" not in e
                         for e in rt):
                    warn(scope, "retry_trace_malformed",
                         f"{task_id}: retry_trace entries missing attempt/kind")
            fv = task.get("forced_verify")
            if fv is not None and not isinstance(fv, bool):
                warn(scope, "forced_verify_type", f"{task_id}: forced_verify={fv!r} (expected bool)")

        # v2.29 (I1/I7): verification_gaps / docs_gaps must be lists when present.
        for gap_field in ("verification_gaps", "docs_gaps"):
            gv = tree.get(gap_field)
            if gv is not None and not isinstance(gv, list):
                warn(scope, f"{gap_field}_type", f"{gap_field} present but not a list")

    return {
        "passed": violations == [],
        "scopes_checked": [s for s, _ in trees],
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--active-plan", default="auto")  # accepted for contract parity
    args = ap.parse_args(argv)

    try:
        state = json.loads(args.state.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — broken state is exit 2 by contract
        print(json.dumps({"passed": False, "error": f"unparseable state.json: {exc}"}))
        return 2

    result = validate(state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
