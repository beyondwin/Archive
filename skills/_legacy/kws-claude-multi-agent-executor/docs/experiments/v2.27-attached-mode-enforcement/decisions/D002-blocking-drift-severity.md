# D002 — Elevate cost/timing drift from WARN to blocking FAIL

**Date**: 2026-06-06
**Status**: Decided

## Context

`per-role-confidence-calibration-20260606-005019` wired all four hooks correctly,
yet still finished with `cost_ledger.totals.dispatches == 0` and `timing.started`
null on all seven tasks. Cause: `phase_boundary.py task-start` (pre-sha +
`timing.started`) and `accumulate_cost.py` (per-dispatch ledger) are mandatory but
expressed as **prose** in `phase-1-task-cycle.md`; the in-session attached
orchestrator drifts past them under context pressure. `finalize_run.py` records
both as **WARN** (`cost_dispatches_zero`, `timing_started_missing`), so
`finalize_run.py --check` returns `passed: true` and the v2.26 Stop gate — which
keys off `finalize_run --check` exit code — lets the stop through.

So even with the Stop gate correctly wired, a fully-drifted attached run finishes
silently green. The gate is sound; its inputs were too lenient.

## Options considered

- **A**: keep WARN, surface drift more loudly in the run summary report. Rejected —
  the summary is prose the user reads after the fact; it does not block a silent
  green finish, which is the actual failure.
- **B**: make the bookkeeping non-skippable by moving it out of prose into control
  flow. Rejected as the *primary* fix: in attached mode the orchestrator *is* the
  control flow (in-session Opus reading prose); there is no non-prose place to put
  it short of a hook, and a hook cannot retroactively know when a task started. (We
  still keep the prose mandate; this ADR is the detection backstop.)
- **C**: elevate `cost_dispatches_zero` and an all-null-`timing.started` aggregate
  to blocking FAIL, each suppressible by an explicit waive flag
  (`cost_tracking_waived` already exists; add `timing_tracking_waived`). The Stop
  gate then blocks a drifted finish.

## Decision

**C.** Specifically in `finalize_run.py`:

- `cost_dispatches_zero`: WARN → FAIL (unchanged `cost_tracking_waived` suppression).
- New aggregate `timing_tracking_absent`: FAIL when ≥1 terminal task and **every**
  terminal task has null `timing.started` and not `timing_tracking_waived`. Keep the
  per-task WARN `timing_started_missing` for partial cases so a lone docs-only task
  without timing does not fail an otherwise-tracked run.

The all-null aggregate (not per-task FAIL) is deliberate: a single missing stamp is
plausibly legitimate; **every** task missing is unambiguous systemic skip.

## Honest limitation

At Stop time the lost data cannot be reconstructed — you cannot know when a task
started after the fact. Blocking does **not** recover data. It converts a silent
green finish into a hard stop that forces the orchestrator to either re-run with
bookkeeping or **explicitly waive with a reason**. The value is "no silent
divergence," matching the v2.26 forcing-function philosophy — not data recovery.

## Consequences

- Both observed drift states (run 1, run 2) now FAIL `finalize_run --check` → the
  Stop gate blocks the stop.
- The clean `interactive_session` run (run 3, populated ledger + timing) still
  passes — verified by regression replay (no false positive).
- Two explicit escape hatches (`cost_tracking_waived`, `timing_tracking_waived`)
  keep intentionally-untracked runs (e.g. a docs-only or dry-run plan) green when
  the operator opts out on purpose.
