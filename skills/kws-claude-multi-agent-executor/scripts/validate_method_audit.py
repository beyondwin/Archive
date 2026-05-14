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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--active-plan", default="auto",
                    choices=["plan1", "plan2", "auto"])
    args = ap.parse_args()

    state = json.loads(args.state.read_text(encoding="utf-8"))
    active = args.active_plan
    if active == "auto":
        active = state.get("active_plan", "plan1")

    if active == "plan2":
        tasks = (state.get("plan2_state") or {}).get("tasks") or {}
    else:
        tasks = state.get("tasks") or {}

    failures = []
    audited = []
    for task_id, task in tasks.items():
        audit = _audit(task_id, task)
        if audit is None:
            continue
        audited.append(audit)
        if audit["missing"]:
            failures.append(audit)

    payload = {
        "passed": failures == [],
        "active_plan": active,
        "audited_count": len(audited),
        "failures": failures,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
