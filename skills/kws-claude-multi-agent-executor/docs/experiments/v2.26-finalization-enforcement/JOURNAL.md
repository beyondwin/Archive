# JOURNAL — Finalization + schema enforcement (v2.26)

Chronological log. Update **as you go**, not at the end.

---

## 2026-06-04

### Two bad runs observed

`source-matching-refinement-20260604-210431` (canonical schema, unfinalized) and
`readmates-member-reading-experience-20260604-210358` (non-canonical schema). Both
`interactive_attached`. Diagnosed root cause as missing **enforcement** of Phase 2
finalization in attached mode — the helpers already exist, nothing forces them to run.

### Gates implemented (TDD)

- `scripts/validate_state_schema.py` (+ tests) — canonical-shape check: empty
  `tasks{}` when declared, `execution_order` without `execution_plan`, risk ∉
  low/mid/high, missing run-level `dispatch_config`/`cost_ledger`, invalid `mode`.
- `scripts/finalize_run.py` (+ tests) — finalization consistency: null `completed_at`
  (FAIL, fixable), `PENDING_BATCH` (FAIL, unfixable), non-terminal task status, cost
  dispatches 0 (WARN, suppressed by `cost_tracking_waived`), missing `timing.started`
  (WARN). `--fix` stamps only `completed_at` (atomic), never clears `PENDING_BATCH`.
- Wired both into `references/phases/phase-2-finalization.md` (Step 1.5 schema gate,
  Step 2 finalize gate) + a SKILL.md Guardrails row.
- Extended `evals/check_skill_contract.py` with `v226_*` helper-exists + wiring checks
  so the prose wiring cannot silently rot.

Regression fixtures built from the two **actual** observed states.

### Pivot — remaining risks must be resolved, not accepted

User directive: resolve ALL the documented remaining risks, not just the
"loud-once-reached" gates. The headline residual risk — a skipped Phase 2 never
invokes the gates (exactly the source-matching failure) — needs a true forcing
function. The Stop-hook declined during design is reinstated under this directive,
designed to address the original cost/intrusiveness objection via a cheap
short-circuit (it only runs the validators once all tasks are terminal). See
decisions/D001.

---

## On close-out

See findings/F01-close-out.md.
