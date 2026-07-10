#!/usr/bin/env python3
"""Reconcile a CPE v3 run; check mode is read-only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cpe_runtime.reconciliation import reconcile
from cpe_runtime.repair import apply_repair, plan_repairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?")
    parser.add_argument("--state")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--repair-safe", action="store_true")
    args = parser.parse_args()
    raw = args.path or args.state
    if not raw:
        parser.error("run directory or --state is required")
    path = Path(raw).expanduser().resolve()
    run_dir = path if path.is_dir() else path.parent
    if args.repair_safe:
        plan = plan_repairs(run_dir)
        applied = [apply_repair(run_dir, action) for action in plan.actions if action in {"rebuild_snapshot", "regenerate_derived_reports"}]
        payload = {"before": plan.as_dict(), "applied": applied, "after": reconcile(run_dir).as_dict()}
    else:
        payload = reconcile(run_dir).as_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    classification = payload.get("classification") or (payload.get("after") or {}).get("classification")
    if any(item.get("code") == "unsupported_schema" for item in (payload.get("findings") or [])):
        return 2
    return 0 if classification == "clean" else 1


if __name__ == "__main__":
    raise SystemExit(main())
