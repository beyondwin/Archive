# D003 — Timing value-sanity, telemetry-coverage, and task-key checks (with severities)

**Date**: 2026-06-07
**Status**: Decided

This ADR groups three smaller checks (gaps 3, 4, 5 in the README) because they
share one theme — *the recorded value is wrong/missing in a way v2.27 does not
inspect* — and because the interesting decision in each is the **severity**, not
the mechanism. They are separated from D001/D002 (the two P0 structural fixes)
because each is independently waivable/removable.

## Context

The three post-v2.27 runs surface three distinct value-integrity defects that
every existing gate passes:

1. **Inverted timing (gap 3).** Run 3 `task_1` has
   `timing.started = 2026-06-06T21:00:00Z` (a KST wall-clock literal with a bogus
   `Z`) but `timing.completed = 2026-06-06T12:02:06Z` — completed *9 hours before*
   started. `finalize_run.py:104-115` only checks `timing.started` is **non-null**;
   it never compares `started <= completed`. The garbage passes. Run 1 shows the
   same family of defect (round-number backfilled timestamps written out of
   order). Root cause: the orchestrator hand-typed timestamp literals into
   state.json instead of letting `phase_boundary.py` stamp UTC atomically.
2. **Telemetry coverage holes (gap 4).** Run 1 has `quality_trend: []` (empty)
   despite 7 reviewed tasks; all three runs have
   `agentlens_orchestration_run: null` (the run was "dark" — no observability
   record). `quality_trend` is appended in **prose** at
   `phase-1-task-cycle.md:200`, so it is skippable exactly like the cost/timing
   prose v2.27 already diagnosed.
3. **Non-canonical task keys (gap 5).** Run 1's `tasks{}` keys are bare integers
   (`"1".."6"`) plus an ad-hoc `"riskclose"`, instead of the canonical `task_<N>`.
   `validate_state_schema.py` has no task-key naming check, so the drift is
   invisible. Bare-int / free-form keys break any tooling that assumes `task_N`.

## Decisions and severities

### Gap 3 — `timing_inverted`: blocking FAIL, **un-waivable**

In `finalize_run.py`'s per-tree task loop, for each terminal task where both
`timing.started` and `timing.completed` parse as ISO-8601, add a FAIL
`timing_inverted` when `started > completed`.

**Severity rationale — why this is NOT gated by `timing_tracking_waived`:**
`timing_tracking_waived` means "I am deliberately not tracking timing" → it
suppresses the *absence* case (all-null `timing.started`, the v2.27 D002 check).
An inverted timestamp is a different claim: timing *is* present, and it is
*physically impossible*. Waiving "I'm not tracking" must not also waive "my data
is corrupt." A waived run that nonetheless emits inverted timestamps is still
broken. So `timing_inverted` fires unconditionally on parseable pairs.

**Honest scope limit:** only fires when *both* timestamps parse as ISO-8601. An
unparseable value falls through to the existing null/absence path (no
`timing_inverted`), so this check never crashes on garbage — it only catches the
specific "two valid timestamps, wrong order" corruption.

Paired with a prose anti-pattern note at `phase-1-task-cycle.md:40-47, 379-385`:
the orchestrator MUST NOT type a timestamp literal into state.json; the only
sanctioned writers of `timing.*` are `phase_boundary.py task-start`/`task-complete`
(UTC, atomic). This addresses the *cause*; the FAIL is the *detection backstop*.

### Gap 4 — coverage: WARN only (`quality_trend_sparse`, `agentlens_run_absent`)

Two mechanisms:

- **Move the writer, don't just detect.** `phase_boundary.py task-complete`, when
  the result object carries a `quality_score`, appends it to
  `<active>.quality_trend` (cap 10, drop oldest) inside the *same atomic write*
  that already records the task result — the exact pattern that fixed
  `timing.completed`. The skippable prose append at `phase-1-task-cycle.md:200` is
  then removed (single writer, unskippable).
- **Detect residual holes as WARN.** `finalize_run.py` adds `quality_trend_sparse`
  (`len(quality_trend) < terminal_tasks_with_review`) and `agentlens_run_absent`
  (`agentlens_orchestration_run` null).

**Severity rationale — WARN, never FAIL:** telemetry is best-effort by the
established v2.10 / v2.17 policy. A missing AgentLens record or a sparse trend
does not mean the *code work* is wrong — it means observability degraded. Blocking
a correctly-implemented run because its telemetry is thin would be the
over-firing D001 just argued against. WARN surfaces it at the Stop gate and in the
Final Summary "Observability" row, so a dark run is visible at close-out rather
than discovered by forensics weeks later — without wedging a good run.

### Gap 5 — `task_key_noncanonical`: WARN only

`validate_state_schema.py` adds a WARN listing any `tasks{}` key not matching
`^task_\d+(_[a-z0-9-]+)?$` (canonical `task_3`, `task_7_remediation`).

**Severity rationale — WARN, not a schema violation:** a finished run whose keys
merely deviate is still a finished run; hard-blocking it at the Stop gate would
strand completed work over a naming nit. WARN surfaces the drift. Promotion to a
hard violation is **deferred** until the prose that *writes* keys is itself
tightened — blocking on a shape the skill's own prose still allows to drift would
be premature. The reinforcing prose (`phase-0-setup.md` / `phase-1-task-cycle.md:391`)
ships now; the gate stays advisory until that prose has settled.

`task_summaries_alongside_tasks` stays a WARN; v2.28 documents `task_summaries` as
a legacy read-mirror (no new writes) but does not remove it — a larger change,
deferred.

## Why grouped, and the severity pattern

The three checks form a deliberate severity ladder that encodes "how certain are
we this is a defect":

| Check | Severity | Certainty it's a real defect |
|-------|----------|------------------------------|
| `timing_inverted` | FAIL (un-waivable) | total — timestamps are physically impossible |
| `quality_trend_sparse` / `agentlens_run_absent` | WARN | partial — telemetry degraded, work may be fine |
| `task_key_noncanonical` | WARN | partial — cosmetic/tooling risk, work is fine |

This mirrors v2.27 D002's reasoning (all-null timing is unambiguous → FAIL; a
single null is plausibly legitimate → WARN): severity tracks certainty, and we
only block when the signal is unambiguous corruption.

## Consequences

- Run 3's inverted `task_1` timing now FAILs `finalize_run --check` (even though
  cost is auto-waived per [D001](./D001-cost-auto-waive-on-agent-path.md)) — the
  honest blocker replaces the structural `cost_dispatches_zero` one.
- Run 1's empty `quality_trend` surfaces as a `quality_trend_sparse` WARN, and its
  bare-int keys as `task_key_noncanonical` WARN — visible at close-out, `passed`
  stays true (no false positive on a finished run).
- All three runs' `agentlens_orchestration_run: null` surfaces as
  `agentlens_run_absent` WARN.
- `quality_trend` becomes unskippable (boundary write) for future runs, closing
  the prose-skip at its source.
- No metered/clean baseline regresses: a normal `started <= completed`, populated
  trend, canonical keys, and a live AgentLens run produce zero new findings.
