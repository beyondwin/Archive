# D002 — Single-plan keeps v2.12 schema; multi-plan introduces `plan_chain[]`

**Status**: Accepted
**Date**: 2026-05-16

## Context

v2.12 schema:
- Single-plan: top-level `state.tasks`, `state.task_summaries`, `state.quality_trend`, etc.
- Two-plan (plan + plan2): all v2.12 fields PLUS `state.plan2_state` nested object with its own `tasks/task_summaries/...`. `state.active_plan ∈ {"plan1", "plan2"}`.

For N≥3 plans, there's no place to put plan 3+'s state. Multiple options:

1. Add `plan3_state`, `plan4_state`, ... as nested fields. Symmetric with `plan2_state`. Schema sprawls.
2. Replace `plan2_state` with `plan_chain[]` and migrate. Every reader of `plan2_state` must update.
3. Hybrid: keep `plan2_state` for backward read, introduce `plan_chain[]` only when N≥2. New code writes `plan_chain`; v2.12 readers see legacy `plan2_state` only on v2.12 state files.

## Decision

Hybrid (option 3) — single-plan runs keep the exact v2.12 schema; multi-plan runs introduce `plan_chain[]`.

**Single-plan invocation** (no `plan2=` and no `plan3+=`):
- Same as v2.12. `state.tasks`, `state.task_summaries`, `state.quality_trend`, `state.active_plan = "plan1"`. No `plan_chain` field written.

**Multi-plan invocation** (any `planN=` for N≥2):
- `state.plan_chain` is the source of truth: array of N entries, each with `{plan_path, spec_path, status, baseline, tasks, task_summaries, risk_levels, task_complexity, compaction_points, execution_plan, global_constraints, quality_trend, low_tasks_pending_verification, last_compaction_after_task, plan_review}`.
- `state.active_plan` is an integer index into `plan_chain` (0, 1, 2, ...).
- Top-level `state.tasks` and similar fields are NOT written by v2.13 for multi-plan runs. Code that needs the active plan's task tree must dereference `state.plan_chain[state.active_plan].tasks`.
- `state.plan2_state` is NOT written by v2.13 — `plan_chain` replaces it. v2.12 state files retain `plan2_state` and are still readable by their original v2.12 code; v2.13 code only reads `plan_chain`.

**Resume protocol detection:**
- `state.plan_chain` present → v2.13 multi-plan run; route through chain.
- `state.plan2_state` present + no `plan_chain` → legacy v2.12 two-plan run.
- Neither + `state.tasks` present → single-plan run (v2.12 or v2.13).

## Consequences

- Single-plan v2.12 benchmark + all v2.12 state files keep working bit-for-bit.
- Multi-plan code path is clean — one tree to dereference, no special-casing index 0 vs index ≥1.
- aggregate.py (v2.12) reads `state.tasks` and `state.plan2_state.tasks`. For v2.12 single-plan runs the script keeps working. For v2.13 multi-plan runs, the script needs an update to also read `state.plan_chain[*].tasks`. This is documented in the v2.13 RUN notes; aggregate.py is in the v2.12 experiment dir and is not silently broken.

## Alternatives considered

- **Pure `plan_chain[]` for all runs (option 2).** Rejected — breaks every Monitor script and aggregate.py at once, even for users who never run multi-plan. Forces a coordinated update.
- **`plan3_state`, `plan4_state`, ... (option 1).** Rejected — schema sprawl, awkward for N=10+, and Cross-Plan Trigger logic forks per index.
