# D001 — Stop-hook forcing function for finalization

**Date**: 2026-06-04
**Status**: Decided

## Context

The v2.26 Phase 2 gates (`validate_state_schema.py` at Step 1.5,
`finalize_run.py --fix` at Step 2) make finalization loud and self-correcting **once
Phase 2 is reached**. But the headline failure they were built for —
`source-matching-refinement-20260604-210431` — is a run that *never entered Phase 2*:
the in-session `interactive_attached` orchestrator stopped right after the last task's
implement step (`current_task: 10, current_step_within_task: 1`) and never walked the
Phase 2 sweep → completed_at stamp. A gate wired only into Phase 2 prose cannot fire
when Phase 2 is skipped. The design recorded this as an accepted remaining risk, with
a Stop-hook noted as the true forcing function but **declined for cost/intrusiveness**.

The second remaining risk — attached-mode schema improvisation (empty `tasks{}`,
`execution_order`, `"verify"` risk) — is detected at Step 1.5 but only if Step 1.5
runs, i.e. only if Phase 2 is entered. Same root cause.

User directive (2026-06-04): resolve **all** remaining risks. This reverses the
earlier Stop-hook decline.

## Options considered

- **A**: keep gates Phase-2-only; accept the skipped-Phase-2 risk (status quo / design
  as-shipped). Rejected — the user explicitly asked to resolve it.
- **B**: write-path enforcement — route every `state.json` write through a canonical
  writer that refuses non-canonical shapes. Prevents improvisation at the source but
  is a large surface change (every inline `jq` R-M-W in the skill), and still does
  nothing about a run that simply *stops early* with a canonical-but-unfinalized state.
- **C**: Stop-hook forcing function — a Claude Code `Stop` hook in the worktree
  `.claude/settings.json` that, when the session tries to end, checks whether the run
  is "done but not finalized" and blocks the stop (exit 2) with corrective guidance.

## Decision

**C**, designed to neutralize the original cost/intrusiveness objection.

`<orch_dir>/hooks/finalization-stop-gate.sh` (materialized at Phase 0 Step 2.5
alongside the existing PreToolUse/PostToolUse/SubagentStop hooks, wired into
`<worktree>/.claude/settings.json` as a `Stop` hook):

1. **Cheap short-circuit.** Read `state.json`. If it cannot be read, or if **any**
   task in the active tree is still non-terminal (not COMPLETE/SKIPPED), exit 0
   immediately — the orchestrator legitimately pauses between turns mid-run. This is a
   single `jq` pass, so the per-turn cost during a run is negligible (the objection).
2. **Full check at the end.** Only once **every** task is terminal does the hook run
   `finalize_run.py --check` and `validate_state_schema.py`. If either reports a
   blocking problem (unfixable FAIL, or any schema violation), exit 2 with the findings
   on stderr so the model is told to complete Phase 2 finalization before stopping.
   Otherwise exit 0.

This fires exactly once, at the real end of the run, in the precise state where the
declined risk bites — not on every intermediate stop. It resolves **both** remaining
risks: the skipped-Phase-2 bypass (the hook runs the gates even if Phase 2 prose never
did) and write-time schema improvisation (the schema validator runs at stop time,
converting a silent divergence into a blocked stop).

## Consequences

- Attached mode now has a real forcing function; a run cannot silently end
  complete-but-unfinalized or non-canonical.
- The hook is advisory-blocking: a determined operator can still bypass (disable the
  hook, or the model can be told to stop anyway), consistent with the rest of the
  worktree hook suite. It is enforcement, not a hard lock.
- The hook depends on both validators existing at their `scripts/` paths and on a
  readable `state.json`; a broken validator degrades to "allow stop" rather than
  trapping the session (fail-open on hook-internal error, fail-closed on detected
  inconsistency).
