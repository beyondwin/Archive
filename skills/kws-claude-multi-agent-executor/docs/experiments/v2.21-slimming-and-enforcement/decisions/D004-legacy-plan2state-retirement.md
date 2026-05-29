# D004 — Retire v2.12 `plan2_state` dual-path via resume migration shim

**Date**: 2026-05-29
**Status**: Decided

## Context

v2.13 introduced `plan_chain[]` as the multi-plan source of truth but kept the
v2.12 `plan2_state` two-plan path "for legacy state.json compatibility." Every
multi-plan region of SKILL.md (active-tree resolution, Phase 2 Step -1 Cross-Plan
Trigger, the `<active>` table, numerous guardrails) now carries **two parallel code
paths**. This doubles the surface area and the divergence risk, and a meaningful
slice of the multi-plan prose exists only to describe the legacy branch.

The legacy path only matters for *resuming a run whose state.json was written by
v2.12* (a two-plan run with `plan2_state`). New runs never write `plan2_state`.

## Options considered

- **A**: keep both paths forever. Status quo tax.
- **B**: drop the legacy path outright. Breaks resume of any in-flight v2.12
  two-plan run.
- **C**: one-time **resume migration shim** — when Phase 0 Step 0 loads a
  state.json containing `plan2_state` and no `plan_chain`, convert it in place to a
  `plan_chain[]` of length 2 (index 0 = top-level fields, index 1 = plan2_state
  fields), set `active_plan` to the integer index, write back, then proceed on the
  single modern path. After the shim, delete all `plan2_state` / `active_plan ==
  "plan2"` branches.

## Decision

**C.** The shim is small, runs only on the legacy-shaped resume, and lets every
downstream branch collapse to the `plan_chain` path. Implement the conversion in a
testable helper (`scripts/migrate_legacy_state.py` or a `state_set` mode) so it can
be unit-tested against a captured v2.12 two-plan state.json fixture.

Precondition check before deleting branches: confirm no live run under
`~/.claude/orchestrator/*/state.json` currently has `plan2_state` non-null without
`plan_chain`. If one exists, migrate or let it finish first.

## Consequences

- Removes a full duplicated code path from SKILL.md and references — meaningful
  slimming on top of item 1, and one fewer "did you update both paths?" trap.
- Single-plan v2.12 schema (no `plan_chain`, top-level `tasks`) is **unaffected** —
  it remains the modern single-plan shape. Only the *two-plan* `plan2_state` shape
  is migrated.
- Adds a migration fixture to the eval/test corpus.

## Open questions

- Where does single-plan top-level-`tasks` live after this? It stays as-is; the
  `<active>` resolution keeps its "neither plan_chain nor plan2_state → top-level"
  branch for single-plan runs. Only the `plan2_state` branch is removed.
