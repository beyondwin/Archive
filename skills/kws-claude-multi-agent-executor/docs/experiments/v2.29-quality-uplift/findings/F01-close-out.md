# F01 — Close-out: v2.29 quality-uplift

**Date**: 2026-06-07
**Decision**: SHIP all of P0/P1/P2 (I1–I11) + record-only I12.

## What shipped

All 12 catalog items, additively (`schema_version` unchanged), in three commits
(v2.29.0 P0 / v2.29.1 P1 / v2.29.2 P2) on branch `v2.29-quality-uplift`, then a
docs-sync commit (version bump 2.28.0→2.29.0, HISTORY/snapshot/decision-log/
state-schema/README).

| Item | Kind | Verification |
|------|------|--------------|
| I1 retry→SKIP | doc | phase-1-task-cycle Step2/3 + SKILL.md guardrails |
| I2 events.jsonl tee | code+doc | +7 phase_boundary tests |
| I3 retry_trace | code+doc | +7 phase_boundary tests |
| I4 build_final_report | code+doc | +12 tests (run_report/1 + md snapshot) |
| I5 build_context_slice | code+doc | +10 tests |
| I6 partial spec re-read | doc | SKILL.md + 2 references |
| I7 failure_summary | code+doc | +4 finalize tests |
| I8 auto_resolved_count | doc+schema | +2 validator tests |
| I9 forced_verify | doc+schema | +1 validator test |
| I10 state_resume_digest | code+doc | +6 tests |
| I11 compaction discipline | doc | phase-transition T3 |
| I12 SDK context-editing | record | D001 ADR |

## Verification evidence

- Full `scripts/` pytest suite green after every bundle (242 → 268 → final count).
- `check_skill_contract.py --skill ./SKILL.md` green (no failures).
- `check_doc_freshness.py` green (versions consistent, HISTORY entry, snapshot,
  decision-log indexed).
- `python3 -m py_compile scripts/*.py` clean.

## Risk dispositions (plan §5)

| Risk | Disposition |
|------|-------------|
| I1 SKIP over-propagation | reuses escalation-cap propagation + reset-before-SKIP; no new behavior |
| I4 markdown drift from prose | snapshot test locks structure+derived fields; free-form sections derived from state, not claimed byte-equal (documented limitation) |
| I6 partial re-read misses structural edit | "regen manifest on structural change" safeguard documented |
| I2 events.jsonl growth | append-only line JSON under `<orch_dir>`, best-effort, no worktree pollution |
| New fields break old readers | all additive, default-absent, `schema_version` unchanged; validator typechecks are WARN-only |
| Orchestrator-prompt emergent behavior | fixture eval gate (`evals/run.sh`) is the adoption gate per Anthropic warning |

## Not done / deferred

- I12 native context-editing — deferred to a future Agent SDK port (D001).
- `aggregate_runs.py` consuming `run_report.json` directly — out of scope per
  plan (I4 ships the artifact; the consumer wiring is a separate change).
- Full `evals/run.sh` LLM judge suite — orchestrator-prompt changes are
  doc-level; deterministic checks (pytest + contract + freshness) cover the code.
  Recommend a fixture-eval pass before relying on the new prose in a live run.
