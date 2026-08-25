# F01 — Close-out: instrumentation integrity (v2.28)

**Date**: 2026-06-07
**Decision**: SHIP

## What shipped

- **D001 — honest cost auto-waive on the agent path.** Phase 0 Step 7 auto-sets
  run-level `cost_tracking_waived=true` + `cost_tracking_waive_reason="agent-dispatch-no-usage"`
  when every role gate is `"agent"` and mode is `interactive_attached` — subscription-pool
  Agent-tool dispatches return no `usage`, so `dispatches:0` is a law of physics, not a
  skip. `finalize_run.py` reads the waive and does not raise the cost FAIL. Both fields
  are run-level and PRESERVED across resume / plan_chain swap / Resume Chain handoff. The
  false "subscription dispatches still report usage" prose in `agent-dispatch.md` /
  `phase-1-task-cycle.md` was removed; `state-schema.md` documents the new field. Any
  metered `api`/`p` gate disables the auto-waive; the Final Summary renders
  `Cost tracking: WAIVED — {reason}`.
- **D002 — Stop-gate all-terminal trigger.** `finalization-stop-gate.sh.template` gained
  a third `elif [ "${TOTAL:-0}" -gt 0 ]` DONE=1 branch: every declared task terminal at
  Stop time forces finalization even when `status` is null and `current_task` is still
  set — closing the run-3 wedge where Phase 2 never ran.
- **D003 — value-sanity FAIL + coverage WARNs + task-key WARN.**
  `finalize_run.py` parses `timing.started`/`completed` via the tolerant `_parse_iso`
  helper and raises an **un-waivable** blocking `timing_inverted` FAIL on
  `completed < started` (corruption, not absent data — no escape hatch); it also emits
  non-blocking `quality_trend_sparse` + `agentlens_run_absent` WARNs for dark telemetry.
  `quality_trend` is now written SOLELY by `phase_boundary.py` task-complete (single
  writer; inline prose append removed). `validate_state_schema.py` matches every task key
  against `TASK_KEY_RE` (`^task_\d+(_[a-z0-9-]+)?$`) and emits a `task_key_noncanonical`
  WARN for non-conformers (e.g. `"1"`, `"riskclose"`).
- **Bookkeeping (this task).** `evals/check_skill_contract.py` gained `v228_*` checks
  (per-file helper-token presence, Stop-gate all-terminal branch, `cost_tracking_waive_reason`
  wired in the corpus, the false usage claim gone); SKILL.md → version `2.28.0` with +5
  Guardrails rows (D001 cost auto-waive; D003 `timing_inverted` un-waivable FAIL,
  coverage WARNs, `task_key_noncanonical`; the D002 nuance was folded into the existing
  Stop-hook row); HISTORY / ARCHITECTURE / decision-log / experiments-index synced;
  `docs/snapshots/v2.28.0.md` added for the doc-freshness milestone gate.

## Verification at close-out

- `python3 evals/check_skill_contract.py --skill SKILL.md` → `passed: true`; all six
  `v228_*` checks true (`v228_helper_contract_scripts_finalize_run.py`,
  `…_validate_state_schema.py`, `…_phase_boundary.py`, `v228_stopgate_all_terminal`,
  `v228_cost_waive_reason_wired`, `v228_no_false_usage_claim`).
- `python3 -m pytest scripts/ -q` → 219 passed / 0 failed (Task 6 changed no script
  behavior — only the contract checker, which is itself a test, plus docs).
- `python3 evals/check_doc_freshness.py` → passes.

The full 3-fixture regression replay (real before/after `finalize_run.py --check`) and
the Stop-gate integration test are the remaining real proof, carried by Task 7.

## Remaining risks (carried forward from the spec, honestly)

From the spec's "Remaining risks" section — these ship as accepted residual risk:

- **Auto-waive hides cost on a run the user *did* want tracked.** Mitigation: only fires
  when no `api`/`p` gate is set AND mode is attached; any metered gate disables it;
  rendered loudly in the Final Summary + D001. The waive is reasoned and discoverable,
  not silent.
- **`timing_inverted` false-positive on legitimate clock skew.** Requires
  `started > completed` on the *same* task (one monotonic clock per run); sub-second skew
  cannot invert. The tolerant parser returns `None` on anything non-ISO, so only
  clearly-bad data fails — but a genuinely pathological host clock that jumps backward
  mid-task would trip it (acceptable: corruption should surface).
- **All-terminal Stop trigger blocks a user who intentionally paused after the last
  task.** That is the intended behavior — finalize is mandatory. The gate's stderr prints
  the `finalize_run --fix` command; fail-open on any hook-internal error keeps it from
  trapping a broken session.
- **Skipped Phase 2 *and* a disabled Stop hook** would still bypass everything — the Stop
  trigger only helps when the hook is wired (the v2.27 D003 `hooks_not_wired` finalize
  backstop covers the wiring case). A run that strips both is out of scope.
- **`quality_trend_sparse` noisy on docs-only runs.** Counts only tasks with a
  `review_tier`/`review`; docs-only tasks without review are excluded from the
  denominator. WARN-only, never blocks.
