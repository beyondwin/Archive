#!/usr/bin/env python3
# DEPRECATED (v3.0 T15 cutover): the CME v3 kernel reimplements this migration in
# scripts/kernel/migrate.py (rules reproduced, not imported). The kernel orchestrator
# does NOT call this script. NOT deleted because it is still referenced by
# evals/check_skill_contract.py and references/cross-cutting/{state-schema,multi-plan-chain}.md
# (v2 docs/eval). Also imports state_set (itself deprecated). Retire with those v2 orphans (T16).
"""One-time resume shim: convert a v2.12 `plan2_state` state.json to `plan_chain`.

v2.13 made `plan_chain[]` the multi-plan source of truth but kept the v2.12
two-plan `plan2_state` path alive purely so an in-flight v2.12 run could still be
resumed. That dual path doubled the surface area of every multi-plan region of
SKILL.md. D004 retires it: on the *next resume* of a legacy-shaped state.json,
this shim rewrites it in place to the modern `plan_chain` shape, after which every
downstream branch collapses to the single `plan_chain` path.

Migration (only when `plan_chain` is ABSENT and `plan2_state` is a non-null obj):
- plan_chain[0]  ← the top-level per-plan fields (plan 1's data) + plan/spec paths
- plan_chain[1]  ← the `plan2_state` fields (plan 2's data)
- active_plan    ← integer index ("plan1"→0, "plan2"→1; already-int preserved)
- top-level per-plan fields and `plan2_state` are removed (they now live in the
  chain; leaving them would re-create the divergence the shim exists to remove).

No-ops (exit 0, "unchanged"):
- `plan_chain` already present (modern multi-plan, or a re-run of this shim).
- `plan2_state` null/absent (single-plan v2.12 — its top-level `tasks` shape is
  the modern single-plan shape and is left exactly as-is).

Run-level fields (cost_ledger, budget_*, timestamps, current_* counters, mode,
branch, worktree, implementer_model, spec_edits, test_command, agentlens_*,
source_repo, context_budget, schema_version, …) are NOT touched — they stay at
the top level where they already belong.

Usage:
    python3 migrate_legacy_state.py --state <orch_dir>/state.json [--dry-run]

Exit codes:
- 0  success (migrated, or no-op) — prints a one-line JSON summary to stdout
- 1  IO / JSON / shape failure (stderr message)
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from pathlib import Path

try:
    import state_set as ss  # type: ignore
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import state_set as ss  # type: ignore


# Per-plan fields and their empty defaults (mirrors the Phase 0 Step 7 schema).
# A field absent on the legacy side is created with this default in the chain
# entry so downstream `<active>.<field>` reads never KeyError.
PER_PLAN_DEFAULTS: dict = {
    "tasks": {},
    "task_summaries": {},
    "quality_trend": [],
    "baseline": None,
    "low_tasks_pending_verification": [],
    "global_constraints": {"shared_files": {}},
    "compaction_points": [],
    "execution_plan": [],
    "risk_levels": {},
    "task_complexity": {},
    "last_compaction_after_task": -1,
    "last_completed_task": None,
    "last_completed_at": None,
    "plan_review": {"status": "SKIPPED", "warnings": []},
    "decisions_register": [],
    "task_header_prefix": "### ",
}


def _build_entry(index: int, source: dict, plan_path, spec_path,
                 status: str, blocked_until) -> dict:
    """Build a plan_chain[] entry, moving known per-plan fields out of `source`
    (mutates `source` by popping them)."""
    entry = {
        "index": index,
        "plan_path": plan_path,
        "spec_path": spec_path,
        "status": status,
        "blocked_until": blocked_until,
    }
    for field, default in PER_PLAN_DEFAULTS.items():
        if field in source:
            entry[field] = source.pop(field)
        else:
            # Copy the default so chain entries never alias the shared template.
            entry[field] = json.loads(json.dumps(default))
    return entry


def _coerce_active_index(active_plan) -> int:
    if isinstance(active_plan, bool):  # bool is an int subclass; reject early
        raise ValueError(f"active_plan must not be a bool: {active_plan!r}")
    if isinstance(active_plan, int):
        return active_plan
    if active_plan == "plan2":
        return 1
    return 0  # "plan1", None, or anything else → plan 1


def migrate(state: dict) -> tuple[bool, str]:
    """Return (changed, reason). Mutates `state` in place when changed."""
    if state.get("plan_chain"):
        return False, "already-plan_chain"
    p2 = state.get("plan2_state")
    if not p2:  # null or absent → single-plan, leave as-is
        return False, "single-plan-no-plan2_state"
    if not isinstance(p2, dict):
        raise ValueError(f"plan2_state is not an object: {type(p2).__name__}")

    entry0 = _build_entry(
        0, state,
        plan_path=state.get("plan"),
        spec_path=state.get("spec"),
        status="running",
        blocked_until=None,
    )
    entry1 = _build_entry(
        1, p2,
        plan_path=p2.get("plan_path"),
        spec_path=p2.get("spec_path"),
        status=p2.get("status", "queued"),
        blocked_until=p2.get("blocked_until"),
    )

    state["plan_chain"] = [entry0, entry1]
    state["active_plan"] = _coerce_active_index(state.get("active_plan"))
    state.pop("plan2_state", None)
    return True, "migrated"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", required=True, help="path to state.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing")
    args = ap.parse_args(argv)

    state_path = Path(args.state)
    if not state_path.is_file():
        print(f"state.json not found at {state_path}", file=sys.stderr)
        return 1

    lock_path = state_path.with_name(state_path.name + ".lock")
    lock = open(lock_path, "w", encoding="utf-8")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        try:
            changed, reason = migrate(state)
        except ValueError as exc:
            print(f"migration failed: {exc}", file=sys.stderr)
            return 1
        if changed and not args.dry_run:
            ss._atomic_write_json(state_path, state)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"state.json read/write failed: {exc}", file=sys.stderr)
        return 1
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()

    print(json.dumps({"changed": changed, "reason": reason,
                      "dry_run": bool(args.dry_run)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
