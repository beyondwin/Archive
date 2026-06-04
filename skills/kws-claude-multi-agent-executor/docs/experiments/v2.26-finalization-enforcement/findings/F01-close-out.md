# F01 — Close-out: finalization + schema enforcement (v2.26)

**Date**: 2026-06-04
**Status**: shipped

## What shipped

Two standalone validators, a Stop-hook forcing function, Phase 2 wiring, a Guardrail,
contract-eval coverage, and regression fixtures built from the two real bad runs.

| Deliverable | Artifact |
|-------------|----------|
| Canonical-shape gate | `scripts/validate_state_schema.py` + `test_validate_state_schema.py` |
| Finalization gate (safe `--fix`) | `scripts/finalize_run.py` + `test_finalize_run.py` |
| Phase 2 wiring | `references/phases/phase-2-finalization.md` Step 1.5 + Step 2 |
| Guardrail | SKILL.md "Finalization gate is mandatory before close-run (v2.26)" |
| Wiring-rot guard | `evals/check_skill_contract.py` `v226_*` checks |
| Forcing function | `<orch_dir>/hooks/finalization-stop-gate.sh` (Phase 0 Step 2.5) |
| New field | run-level `cost_tracking_waived` (ARCHITECTURE §5) |

## Evidence

The two observed 2026-06-04 states reproduced as fixtures:

- `SOURCE_MATCHING_BAD` — `finalize_run` flags `verifier_pending_batch` +
  `completed_at_null` (FAIL), `cost_dispatches_zero` + `timing_started_missing` (WARN);
  `--fix` stamps `completed_at` but leaves `PENDING_BATCH` (still exit 1).
- `READMATES_BAD` — `validate_state_schema` flags `tasks_empty_but_declared`,
  `execution_order_without_plan`, `risk_value_invalid`, plus
  `missing_dispatch_config` / `missing_cost_ledger`.

Both validators were smoke-tested against the operator's actual run files (read-only,
`--check`) and exited 1 with the documented findings.

## Remaining-risk resolution

The design (`docs/superpowers/specs/2026-06-04-executor-finalization-enforcement-design.md`)
recorded two remaining risks under the Phase-2-only gating. Per the 2026-06-04 user
directive, both are now **resolved** rather than accepted, via the D001 Stop-hook
forcing function:

1. **Skipped Phase 2 bypasses the gate** — RESOLVED. The Stop hook runs both
   validators at session-stop once all tasks are terminal, even if Phase 2 prose never
   executed. The run cannot end complete-but-unfinalized.
2. **Attached-mode schema improvisation not caught until Phase 2** — RESOLVED. The same
   Stop hook runs `validate_state_schema.py` at stop time, so a non-canonical state is
   blocked at the end of the run regardless of whether Phase 2 was entered.

Residual (acknowledged, not a gap): the hook is advisory-blocking like the rest of the
worktree hook suite — a determined operator can disable it. It is enforcement, not a
hard lock. Fail-open on hook-internal error (broken validator / unreadable state →
allow stop), fail-closed on detected inconsistency (→ block stop).

## Verification

- `pytest scripts/test_validate_state_schema.py scripts/test_finalize_run.py` green.
- Full `pytest scripts/` — no regressions.
- `check_skill_contract.py` — `passed: true`, incl. all `v226_*` checks.
- `check_doc_freshness.py` — green at v2.26.0 (README + HISTORY + snapshot consistent).
