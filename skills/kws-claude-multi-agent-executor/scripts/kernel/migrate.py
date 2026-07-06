#!/usr/bin/env python3
"""migrate.py — CME v3.0 state migration shim.

Provides to_v3(old_state) which converts v2.x state dicts to v3 schema.

Migration rules ported from scripts/migrate_legacy_state.py (kept in place until T15).
Do NOT import migrate_legacy_state — rules are reproduced here.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Known v3 top-level field names.
# Any field NOT in this set is moved to state["legacy"].
# IMPORTANT: plan_chain / active_plan are included so the plan2_state migration
# output does not get swept into legacy.
# ---------------------------------------------------------------------------

_V3_TOP_LEVEL_KNOWN = frozenset({
    # identity / infra
    "schema_version",
    "run_id",
    "source_repo",
    "branch",
    "worktree",
    "orchestrator_dir",
    # mode / transport
    "mode",
    "transport_default",
    # model / dispatch
    "implementer_model",
    "parallel",
    "dispatch_config",
    # timing
    "timestamps",
    # cost
    "cost_ledger",
    # plan / spec
    "plan",
    "spec",
    # per-plan task data (single-plan lives at top level)
    "tasks",
    "task_summaries",
    "quality_trend",
    "execution_plan",
    "risk_levels",
    "task_complexity",
    # multi-plan chain
    "plan_chain",
    "active_plan",
    # metadata
    "spec_manifest",
    "decisions_register",
    "run_quality",
    "completion_audit",
    "drift",
    # status
    "status",
    "current_task",
    "last_completed_task",
    # legacy preserve bucket
    "legacy",
})

# ---------------------------------------------------------------------------
# Per-plan fields (mirrored from migrate_legacy_state.PER_PLAN_DEFAULTS)
# ---------------------------------------------------------------------------

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


def _build_chain_entry(index: int, source: dict, plan_path, spec_path,
                       status: str, blocked_until) -> dict:
    """Build a plan_chain[] entry, popping known per-plan fields from source."""
    entry: dict = {
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
            entry[field] = json.loads(json.dumps(default))
    return entry


def _coerce_active_index(active_plan) -> int:
    """Coerce legacy active_plan value to integer index."""
    if isinstance(active_plan, bool):
        raise ValueError(f"active_plan must not be a bool: {active_plan!r}")
    if isinstance(active_plan, int):
        return active_plan
    if active_plan == "plan2":
        return 1
    return 0  # "plan1", None, anything else → 0


def _migrate_plan2_state(state: dict) -> None:
    """Port plan2_state to plan_chain in place (mirrors migrate_legacy_state.migrate).

    Called only when plan_chain is absent and plan2_state is a non-null object.
    Mutates state in place.
    """
    p2 = state.get("plan2_state")
    if not p2:
        return
    if not isinstance(p2, dict):
        raise ValueError(f"plan2_state is not an object: {type(p2).__name__}")

    # Work on a shallow copy of state so we can pop per-plan fields.
    # _build_chain_entry pops from the dict it receives, so we pass state directly
    # (which is the dict we're mutating) for entry0, and p2 for entry1.
    entry0 = _build_chain_entry(
        0,
        state,
        plan_path=state.get("plan"),
        spec_path=state.get("spec"),
        status="running",
        blocked_until=None,
    )
    entry1 = _build_chain_entry(
        1,
        p2,
        plan_path=p2.get("plan_path"),
        spec_path=p2.get("spec_path"),
        status=p2.get("status", "queued"),
        blocked_until=p2.get("blocked_until"),
    )

    state["plan_chain"] = [entry0, entry1]
    state["active_plan"] = _coerce_active_index(state.get("active_plan"))
    state.pop("plan2_state", None)


def to_v3(old_state: dict) -> dict:
    """One-way conversion of a v2.x (or version-less) state dict to v3.

    Rules:
    1. If schema_version >= 3: return as-is (passthrough, no copy).
    2. Otherwise (absent or < 3):
       a. If plan_chain absent AND plan2_state is non-null: migrate plan2_state
          to plan_chain (2-element list) following the v2.21 D004 rules.
       b. Set schema_version = 3.
       c. Move any top-level fields not in the v3 known set to state["legacy"].

    Mutates and returns the same dict object.
    """
    sv = old_state.get("schema_version")
    if isinstance(sv, int) and sv >= 3:
        return old_state  # passthrough

    # Work on a mutable reference (we mutate in place)
    state = old_state

    # --- Step a: plan2_state migration ---
    if not state.get("plan_chain") and state.get("plan2_state"):
        _migrate_plan2_state(state)

    # --- Step b: set schema_version ---
    state["schema_version"] = 3

    # --- Step c: sweep unknown fields to legacy ---
    unknown_keys = [k for k in list(state.keys()) if k not in _V3_TOP_LEVEL_KNOWN]
    if unknown_keys:
        legacy = state.setdefault("legacy", {})
        for k in unknown_keys:
            legacy[k] = state.pop(k)

    return state
