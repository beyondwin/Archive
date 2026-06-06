# D002 — Stop-gate trigger on "all declared tasks terminal"

**Date**: 2026-06-07
**Status**: Decided

## Context

The v2.26 Stop hook (`finalization-stop-gate.sh`) is the forcing function that
blocks a session from stopping while a run is "done but not finalized." Its
`DONE=1` decision keys on a **prose-set end-signal**:

```sh
if [ "$RSTATUS" = "COMPLETE" ]; then DONE=1            # status==COMPLETE
elif [ "$CUR" = "null" ] && [ "$LCT" = "set" ]; then DONE=1   # current_task cleared
fi
```

(`finalization-stop-gate.sh.template:65-74`.) Both conditions are written by the
orchestrator in prose — `status=COMPLETE` is set in Phase 2, `current_task=null`
is cleared at finalization. Run 3 (`session-package-…-205440`) exposes the hole:

- all 16 tasks `COMPLETE` (every task terminal),
- `status: null` (Phase 2 never ran),
- `current_task: 16`, `last_completed_task: task_16` (pointer never cleared).

It matches **neither** condition → `DONE=0` → the gate exits 0 → the session
stops with a fully-worked but unfinalized run. The gate is supposed to catch
exactly "Phase 2 was skipped," but it can only detect it via signals that Phase 2
itself sets. The detector depends on the thing it is detecting.

## Options considered

- **A — Make the orchestrator always clear `current_task` / set `status`.** Reject
  as the gate fix. That is more prose discipline of the same kind that already
  failed; the whole point of the Stop gate is to backstop missing prose. Tightening
  the prose is worth doing, but it cannot be what the *detector* relies on.
- **B — Trigger on a wall-clock idle / "no recent writes" heuristic.** Reject.
  Fragile, time-dependent, and false-positives on a slow legitimate run.
- **C — Trigger on structural completeness: every declared task terminal.** When
  the Stop hook fires (the session is genuinely ending) and `NONTERM==0 &&
  TOTAL>0`, the run *must* finalize — independent of any prose-set signal.

## Decision

**C.** Add a third `DONE=1` condition to the Stop-gate template:

```sh
elif [ "$NONTERM" = "0" ] && [ "$TOTAL" -gt 0 ]; then DONE=1   # all declared tasks terminal
```

Rationale for why this is sound (no false positive on the legitimate path):

- The Stop hook fires **only when the session is actually ending**. A run that is
  about to execute Phase 2 does not Stop — it runs Phase 2, sets
  `status=COMPLETE`, *then* stops, and the existing first condition catches it
  cleanly (the run is finalized, so the full gates pass → exit 0).
- Therefore "all declared tasks terminal **at Stop time**" is unambiguous
  evidence that the session is ending without Phase 2 having run. That is exactly
  the run-3 failure, and exactly what should be blocked.
- The `TOTAL>0` guard preserves the fresh-run exemption: a run with no tasks
  (`tasks:{}`) has `NONTERM==0` vacuously, but `TOTAL==0`, so it is never "done."
  A mid-flight run with any non-terminal task has `NONTERM>0` and is untouched.

This is a structural trigger layered *over* the prose triggers, not a replacement:
`status=COMPLETE` and `current_task=null` still fire `DONE=1` for runs that do set
them. The third condition only adds coverage for the "worked everything, never
finalized" shape the first two miss.

## Honest limitation

The trigger fires `DONE=1`, which then runs the **existing** full gates
(`finalize_run.py --check` + `validate_state_schema.py`). It does not itself
finalize anything — it blocks the stop (exit 2) and tells the orchestrator to run
Phase 2 / `finalize_run.py --fix`. If those gates have their own gaps, this
trigger surfaces the run to them but inherits their limits. It is a *detection*
fix (catch the skipped-Phase-2 shape), not a new finalizer.

## Consequences

- Run 3 (all-terminal, `status:null`, `current_task` set) now hits the third
  condition → full gates run → exit 2 → the stop is blocked until Phase 2
  completes. The previously-silent unfinalized finish is caught.
- Run 2 (all-terminal, `status:null`) is likewise now force-finalized.
- Run 1 (`status:COMPLETE`, clean) still matches the **first** condition and
  passes the gates → exit 0. No false positive on a properly finished run.
- A fresh run (`tasks:{}`, `TOTAL==0`) and any mid-flight run (`NONTERM>0`) remain
  exit 0 — the cheap short-circuit is unchanged for the common case.
- Documented in `phase-0-setup.md:161` and `safety-hooks.md` so the third
  condition is discoverable, not a silent template edit.
