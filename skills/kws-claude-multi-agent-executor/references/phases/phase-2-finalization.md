# Phase 2: Finalization — v3.0 (kernel-owned)

> **v3.0 cutover.** Finalization is no longer a prose procedure the orchestrator
> improvises. The kernel emits `{"action":"finalize"}` from `transitions.decide` when
> all tasks are terminal and zero PENDING_BATCH remain; the orchestrator then runs
> `kernel.py finalize`, which owns the entire close-out sequence.

**What `kernel.py finalize` does** (`kernel.py::handle_finalize`):

1. `drift.check` — blocking drift → `{"error":"finalize_refused_blocking_drift", …}`,
   exit 3. **Hard halt** — resolve the drift, do NOT force-finalize (`SKILL.md §⑤`).
2. Method-audit checklist (non-blocking; surfaces `method_audit_warnings`).
3. Stamp `timestamps.completed_at` (set-if-absent).
4. Build `run_quality` (`quality.build_run_quality`) + `completion_audit`
   (`quality.build_completion_audit` — lingering PENDING_BATCH or SKIPPED blocks the
   release grade).
5. Set `status:"FINALIZED"`; emit `kws-cme.phase_2_complete`.
6. Return `{"status":"finalized","grade","completion_passed","method_audit_warnings"}`.

**This return is the loop-exit signal** (`SKILL.md §③`). After it, report the run
summary (grade, worktree path, gaps) to the user. Never re-run `next` (it re-emits
`finalize`) and never auto-delete the worktree.

**LOW batch drain before finalize.** If any PENDING_BATCH task lingers, `decide`
returns a batch-verify dispatch (not `finalize`) and `check-stop` blocks the stop with
`batch_drain_pending` — so LOW tasks are always verified before the run finalizes.

Multi-plan `plan_chain` advance mechanics live in
[`../cross-cutting/multi-plan-chain.md`](../cross-cutting/multi-plan-chain.md).
