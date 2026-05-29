# D001 — `scripts/state_set.py`: one helper for active-tree writes

**Date**: 2026-05-29
**Status**: Decided

## Context

Every Phase 1 / Transition / Phase 2 state write must go through the `<active>`
resolution rule (top-level vs `plan2_state` vs `plan_chain[active]`). SKILL.md
repeats this rule dozens of times in prose and warns it is "not optional —
hard-coding `state.tasks` silently corrupts the chain." Yet the orchestrator
performs each write by hand with inline `jq` + Write-then-readback. This is:

- error-prone (the exact footgun the prose warns about),
- verbose (a large fraction of the per-task prose is R-M-W boilerplate),
- unenforceable (no way to eval-check that a write resolved the active tree).

`accumulate_cost.py` already proved the pattern: a flock-guarded helper that owns
the R-M-W so the orchestrator just supplies values.

## Options considered

- **A**: keep inline jq + prose rule. Status quo.
- **B**: a generic `state_set.py --field <dotpath> --value <v>` that resolves the
  active tree internally and does flock R-M-W + readback.
- **C**: many narrow helpers (state_set_task_status, state_set_timing, ...).

## Decision

**B.** One helper:

```
python3 scripts/state_set.py --state <path> \
  --field "tasks.task_3.timing.completed" \
  ( --value <json> | --now | --inc <n> | --append-json <json> | --setdefault-json <json> )
  [--plan-scope active|run]   # default active
```

Contract:
- `--field` is a dot-path *relative to the active tree* by default. A leading
  `state.` (or `--plan-scope run`) forces a top-level/run-level write (for fields
  like `timestamps.completed_at`, `cost_ledger`, `mode`).
- Active-tree resolution mirrors the SKILL.md table: `plan_chain[active]` if
  `plan_chain` present; else `plan2_state` if `active_plan=="plan2"`; else
  top-level. After D004 (legacy retirement) the `plan2_state` branch is removed.
- Value modes: `--value` (raw JSON), `--now` (ISO-8601 UTC), `--inc` (numeric
  increment, creating missing as 0), `--append-json` (append to list, create []),
  `--setdefault-json` (write only if absent — for legacy backfill).
- flock on `<state>.lock`; write to temp + atomic rename; read back and re-parse;
  exit non-zero with diagnostic on any failure.
- Intermediate path segments are auto-created as objects.

## Consequences

- Enables: deterministic eval check ("did the run use state_set for task writes?"),
  large prose reduction in Phase 1/Transition/Phase 2, removal of the hand-jq
  active-tree footgun.
- Commits: the helper becomes load-bearing for state integrity. Must be tested
  hard (multi-plan resolution, concurrent flock, missing-path creation, readback
  failure) before wiring into SKILL.md.
- The state-file-write hard-halt guardrail now means "state_set exited non-zero".

## Open questions

- Does the orchestrator still ever need a raw multi-field write in one shot? If so
  add `--patch-json '{...}'` (deep-merge into active tree). Defer until a call site
  needs it.
