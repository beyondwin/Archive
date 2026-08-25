# F01 — Close-out: attached-mode enforcement gaps (v2.27)

**Date**: 2026-06-06
**Decision**: SHIP

## What shipped

- `scripts/materialize_worktree_hooks.py` (+ 15 tests) — deep-merge worktree
  settings.json hooks, preserve repo keys (`permissions`/`$schema`/other hook
  events), self-assert Stop gate, `--check` preflight. Closes the run-2
  hook-wiring loss (D001).
- `scripts/finalize_run.py` — `cost_dispatches_zero` and new
  `timing_tracking_absent` are blocking FAIL unless `cost_tracking_waived` /
  `timing_tracking_waived`. Per-task `timing_started_missing` stays WARN for
  partial misses. Closes the run-1 silent-green drift (D002).
- `scripts/finalize_run.py` — new `hooks_not_wired` blocking FAIL (unless
  `hooks_wiring_waived`): reuses `materialize_worktree_hooks.check_problems` to
  assert the worktree settings.json wires the four hooks / Stop gate, riding both
  finalize call sites (Stop gate + Phase 2 Step 2 prose). Skips silently when the
  settings.json is absent/unparseable so replays do not false-positive. Closes the
  skipped-Step-2.5 bootstrap residual (D003).
- Phase 0 Step 2.5 + Phase 1 Task-1 preflight + `safety-hooks.md` wired to the
  script; SKILL.md Guardrails (+2 rows) + version 2.27.0; README version bump +
  `docs/snapshots/v2.27.0.md`; HISTORY/ARCHITECTURE/decision-log/experiments-index
  synced.

## Proof — real before/after replay

Ran the committed (HEAD, pre-v2.27) vs the new `finalize_run.py --check` against
the three actual 2026-06-06 runs' `state.json`, plus the schema validator
(unchanged) for context:

| Run | finalize BEFORE | finalize AFTER | schema (unchanged) | gate effect |
|-----|-----------------|----------------|--------------------|-------------|
| per-role-confidence-…005019 | `passed:true` (`WARN:timing_started_missing`) | **`passed:false`** (`FAIL:timing_tracking_absent`) | `passed:true` | was fully green on both gates → **silent green finish**; now finalize FAIL → Stop gate blocks. Cost suppressed by `cost_tracking_waived` — the waive hatch works. |
| readmates-host-prep-…003707 | `passed:true` (`WARN:cost_dispatches_zero`, `WARN:timing_started_missing`) | **`passed:false`** (`FAIL:cost_dispatches_zero`, `FAIL:timing_tracking_absent`, `FAIL:hooks_not_wired`) | `passed:false` (`missing_cost_ledger`) | schema already blocked today; finalize now blocks too (defense in depth). The new D003 `hooks_not_wired` FAIL also catches this run's root cause — its worktree settings.json wired **zero** hooks — at finalize time, not just at materialization. |
| plan-20260604-234058 (clean `interactive_session`) | `passed:true` (no findings) | `passed:true` (no findings) | `passed:true` | **no false positive** — populated dispatches + timing, and the legacy run *did* wire all four hooks (incl. the v2.26 Stop gate), so `hooks_not_wired` does not fire. |

Headline: run-1 is the case v2.26 could not catch — it finished *fully green* on
both finalize and schema (it even set `cost_tracking_waived`), so only the
null-timing drift remained to catch it. After v2.27 it is a blocking
`timing_tracking_absent` FAIL, and the existing Stop gate turns that into a hard
halt.

Stop-gate integration (`test_finalization_stop_gate.py`): `DRIFT_ONLY`
(canonical + finalized except dispatches 0 + all-null timing) → exit 2 (blocks);
`DRIFT_WAIVED` (both waives set) → exit 0 (allows). Confirms the elevated
severities reach through the unchanged v2.26 gate, and the waive hatches reach
back through it.

## Test summary

- `test_materialize_worktree_hooks.py` — 15 pass (incl. ReadMates-shape
  regression: `permissions` + `$schema` preserved AND 4 hooks present;
  idempotency; unparseable-refusal; `--check` Stop-missing).
- `test_finalize_run.py` — 18 pass (2 updated for cost→FAIL; 5 D002:
  RUN1/RUN2/RUN3, timing-waive, partial-timing-stays-WARN; 5 D003:
  unwired-FAIL, wired-pass, waive-suppresses, absent-settings-skips,
  no-worktree-key-skips).
- `test_finalization_stop_gate.py` — 11 pass (7 existing + DRIFT_ONLY blocks /
  DRIFT_WAIVED allows + D003 unwired-hooks-blocks / unwired-hooks-waived-allows).
- Full suite: `pytest scripts/` → 204 pass; `git diff --check` clean.

## Remaining risk

Two items were called out at design time. Their disposition:

**Risk 1 — lost timing/cost data is unrecoverable at Stop time. By design; not
code-resolvable.** The D002 gate forces fix-or-waive, not *recovery* — reconstructing
`timing.started` / cost ledger entries that were never written is an explicit
non-goal. The v2.26 philosophy is a loud, self-correcting halt, not a data-recovery
mechanism. The correct and already-shipped behavior is: a drifted run can no longer
finish silently green; the orchestrator must either re-run with bookkeeping intact
or explicitly waive with a reason. Nothing further to resolve here.

**Risk 2 — a run that skips Phase 0 Step 2.5 wires no Stop gate at all (the
bootstrap problem). Now resolved by the D003 finalize-time backstop.** Previously
the only defenses against an unwired worktree were the Step 2.5 write and the
Phase 1 `--check` preflight — both prose-invoked, so an orchestrator that skipped
Step 2.5 entirely wired no Stop gate and nothing in-band caught it. D003 adds a
`hooks_not_wired` blocking FAIL that rides the **Phase 2 Step 2 `finalize_run.py
--fix`** call site (which is prose, but a distinct skip from Step 2.5): even with
no Stop gate wired, reaching Phase 2 finalize now blocks a finish whose worktree
settings.json is missing the four hooks. The replay confirms it fires on run-2
(zero hooks) and stays silent on the clean run-3 and on cleaned/replayed worktrees.

**Residual (bounded, accepted).** A run that skips Step 2.5 **and** the Phase 1
preflight **and** Phase 2 finalize wholesale still wires and asserts nothing — but
that is "ignore the skill's control flow entirely," outside what any in-band
mechanism can catch. D003 shrinks the bootstrap gap from "skip one prose step" to
"skip every prose enforcement point," which is the cheapest backstop available
without a host-level (out-of-band) hook.

## advisor

advisor tool unavailable in the execution environment; recorded per AGENTS.md.
