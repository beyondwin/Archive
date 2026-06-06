# D003 — Finalize-time hooks-wired backstop

**Date**: 2026-06-06
**Status**: Decided

## Context

D001 moved the worktree `settings.json` write into `materialize_worktree_hooks.py`
(deep-merge, Stop-gate self-assert) and added a `--check` preflight that the
Phase-1 prose runs once before Task 1. That closes the *malformed-write* gap (the
run-2 hand-write that preserved `permissions` but dropped all four hooks).

It does not close the *skipped-write* gap. Both Phase 0 Step 2.5 (the materialize
call) and the Phase-1 `--check` preflight are prose-invoked in attached mode. If
the orchestrator drifts past **both** under context pressure, no hooks are ever
wired — including the v2.26 Stop gate, the one forcing function meant to catch a
degraded finish. The F01 close-out recorded this as accepted residual risk: "a run
that skips Step 2.5 entirely wires no Stop gate at all."

This is a bootstrap problem. The Stop gate can only block a degraded finish if it
was itself installed, and installation is prose. Inside attached mode there is no
mechanical trigger that does not itself depend on a prose step.

## Options considered

- **A**: accept the residual as documented (status quo F01). Rejected — the user
  asked to resolve remaining risks, and there is a cheap independent backstop that
  strictly shrinks the gap.
- **B**: have a hook assert hooks-are-wired. Rejected — circular. Every hook
  (`Stop`, `SubagentStop`, …) only fires if hooks were already wired, so it cannot
  detect its own absence.
- **C**: assert hooks-are-wired inside `finalize_run.py`. `finalize_run.py` is
  invoked from **two** sites — the Stop gate hook *and* Phase 2 Step 2 prose
  (`phase-2-finalization.md`). The Phase-2 call is a *different* prose step than
  Step 2.5 / the preflight, so a run that skips Step 2.5 but reaches Phase 2
  finalize is now caught. The check rides existing call sites — no new invocation
  to skip.

## Decision

**C.** In `finalize_run.py`, reusing `materialize_worktree_hooks.check_problems`
(single source of truth for "wired"):

- Read `<state.worktree>/.claude/settings.json`. If present and parseable but
  missing any of the four events or the `Stop` → `finalization-stop-gate.sh`
  reference → **FAIL** `hooks_not_wired`, unless `hooks_wiring_waived`.
- **Skip silently** (no finding, never a FAIL) when the check cannot run: no
  `worktree` field, file absent, or unparseable. A replayed or cleaned-up worktree
  must not false-positive off-host; the strict unparseable→fail stance stays in the
  `--check` preflight where it runs against the live host.

The orchestrator must now skip Step 2.5 **and** the preflight **and** the Phase 2
finalize call to escape — three independent prose steps, with the finalize check
mechanical once finalize runs.

## Why skip-on-uninspectable (not fail)

The same `finalize_run.py` runs against historical `state.json` during regression
replay and may run on a host where the worktree was deleted after the run. Failing
on "settings.json not found" would fabricate findings for every replay and every
post-cleanup invocation. The genuine bad state — settings.json *exists and parses*
but lacks the Stop gate — is exactly run-2's on-disk shape and is caught.

## Consequences

- Real before/after replay against the three 2026-06-06 runs:
  - run-1 (per-role): hooks wired on disk → no `hooks_not_wired`; stays FAIL on
    `timing_tracking_absent` (D002).
  - run-2 (readmates): settings.json on disk is `{$schema, permissions}` with **no
    hooks** → newly FAILs `hooks_not_wired` (its root cause now caught at finalize
    time too), alongside `cost_dispatches_zero` + `timing_tracking_absent`.
  - run-3 (legacy `interactive_session`): worktree settings.json genuinely wires all
    four hooks → no `hooks_not_wired`; stays `passed: true` — **no false positive.**
- New escape hatch `hooks_wiring_waived` (mirror of the D002 waives) for contexts
  where the worktree is intentionally absent/uninspectable.

## Honest limitation

This does not close the bootstrap fully: a run that skips Step 2.5 **and** the
preflight **and** Phase 2 finalize entirely still wires nothing and runs no gate —
but that is "ignore the skill wholesale," outside what any in-band mechanism can
catch. D003 shrinks the realistic residual (skip the two wiring steps but still
finalize) to a hard FAIL.
