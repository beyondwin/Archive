#!/usr/bin/env python3
"""Validate method_audit fields on a completed kws-claude-multi-agent-executor run.

Exit 0: all completed tasks have required methods applied or waived.
Exit 1: at least one task is missing a required method without a waiver.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EXECUTABLE_REQUIRED = ["test-driven-development", "verification-before-completion", "code-review-pass"]
DOCS_ONLY_REQUIRED = ["verification-before-completion"]


def _is_docs_only(task: dict[str, Any]) -> bool:
    files = task.get("files", [])
    files_test = task.get("files_test")
    if files_test == []:
        return True
    if files_test is None and files and all(str(f).endswith(".md") for f in files):
        return True
    return False


def _required_for(task: dict[str, Any]) -> set[str]:
    return set(DOCS_ONLY_REQUIRED if _is_docs_only(task) else EXECUTABLE_REQUIRED)


def _audit(task_id: str, task: dict[str, Any]) -> dict[str, Any] | None:
    if task.get("status") != "COMPLETE":
        return None
    audit = task.get("method_audit") or {}
    required = _required_for(task)
    applied = {entry.get("skill") for entry in (audit.get("applied") or [])}
    waived = {entry.get("skill") for entry in (audit.get("waived") or [])}
    missing = sorted(required - applied - waived)
    return {
        "task_id": task_id,
        "risk": task.get("risk"),
        "files_test": task.get("files_test"),
        "required": sorted(required),
        "applied": sorted(applied),
        "waived": sorted(waived),
        "missing": missing,
    }


def _collect_task_trees(state: dict[str, Any], active_arg: str) -> list[tuple[str, dict[str, Any]]]:
    """Return a list of (scope_label, tasks_dict) tuples to audit.

    v2.13 multi-plan (state.plan_chain present): audit every plan in the chain
      whose tasks dict is non-empty. Each tuple is ("plan_chain[N]", tasks).
    v2.12 legacy two-plan (state.plan2_state present): audit top-level + plan2_state.
    Single-plan: audit top-level tasks only.

    --active-plan arg restricts scope:
      "auto" → audit all plans with tasks
      "plan1" → top-level only (legacy)
      "plan2" → plan2_state only (legacy)
      "0", "1", "2", ... → that plan_chain index only (v2.13)
    """
    chain = state.get("plan_chain")
    if chain:
        if active_arg == "auto":
            return [
                (f"plan_chain[{entry.get('index', i)}]", entry.get("tasks") or {})
                for i, entry in enumerate(chain)
                if entry.get("tasks")
            ]
        try:
            idx = int(active_arg)
        except ValueError:
            return []  # asking for plan1/plan2 on a chain run — return nothing
        if 0 <= idx < len(chain):
            return [(f"plan_chain[{idx}]", chain[idx].get("tasks") or {})]
        return []
    # Legacy paths
    if active_arg == "auto":
        out: list[tuple[str, dict[str, Any]]] = [("plan1", state.get("tasks") or {})]
        p2 = (state.get("plan2_state") or {}).get("tasks") or {}
        if p2:
            out.append(("plan2", p2))
        return out
    if active_arg == "plan2":
        return [("plan2", (state.get("plan2_state") or {}).get("tasks") or {})]
    return [("plan1", state.get("tasks") or {})]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--active-plan", default="auto",
                    help="auto (all plans), plan1, plan2, or chain index (0, 1, 2, ...)")
    args = ap.parse_args()

    state = json.loads(args.state.read_text(encoding="utf-8"))
    trees = _collect_task_trees(state, args.active_plan)

    failures = []
    audited = []
    for scope, tasks in trees:
        for task_id, task in tasks.items():
            audit = _audit(task_id, task)
            if audit is None:
                continue
            audit["scope"] = scope
            audited.append(audit)
            if audit["missing"]:
                failures.append(audit)

    payload = {
        "passed": failures == [],
        "scopes_audited": [scope for scope, _ in trees],
        "audited_count": len(audited),
        "failures": failures,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
