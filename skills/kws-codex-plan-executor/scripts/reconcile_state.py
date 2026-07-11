#!/usr/bin/env python3
"""Reconcile a CPE v3 run; check mode is read-only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cpe_runtime.reconciliation import reconcile
from cpe_runtime.repair import apply_repair, plan_repairs


def _run_dir(run_dir: str | None, state: str | None) -> Path:
    if run_dir is not None:
        path = Path(run_dir).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("run_dir_missing")
        return path
    assert state is not None
    path = Path(state).expanduser().resolve()
    if path.name != "state.json" or not path.is_file():
        raise ValueError("state_path_invalid")
    return path.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--run-dir")
    target.add_argument("--state", help="compatibility alias for an exact v3 state.json path")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--repair-safe", action="store_true")
    args = parser.parse_args()
    try:
        run_dir = _run_dir(args.run_dir, args.state)
        if args.repair_safe:
            plan = plan_repairs(run_dir)
            applied = [
                apply_repair(run_dir, action)
                for action in plan.actions
                if action in {"rebuild_snapshot", "regenerate_derived_reports"}
            ]
            payload = {"before": plan.as_dict(), "applied": applied, "after": reconcile(run_dir).as_dict()}
        else:
            payload = reconcile(run_dir).as_dict()
    except (OSError, ValueError) as exc:
        code = str(exc) or "reconciliation_failed"
        payload = {"classification": code, "passed": False, "errors": [code]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    report = payload.get("after") if isinstance(payload.get("after"), dict) else payload
    classification = report.get("classification")
    if classification == "blocking_drift" and any(
        item.get("code") == "unsupported_schema" for item in report.get("findings", [])
    ):
        return 2
    return 0 if classification in {"clean", "clean_incomplete"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
