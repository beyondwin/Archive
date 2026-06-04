# F01 — v2.25 Subscription-pool Agent Dispatch: Close-out

**Decision: SHIP**

**Date**: 2026-06-04
**Status**: FINAL
**Outcome**: SHIPPED — agent-tool dispatch on the subscription pool is now the default for all role gates.

## What shipped

A third dispatch transport `"agent"` was added to every `state.dispatch_config`
role gate, alongside the existing `"p"` and `"api"` values. The `"agent"`
transport dispatches the role **in-session via the Agent tool on the
subscription pool** — the same path already used by the Implementer and Combined
Reviewer — so a bare invocation runs every role on the Max/Pro subscription with
`$0` metered spend.

- **All seven role gates default to `"agent"`** — `plan_reviewer`,
  `verifier_batch`, `verifier_per_task`, `transition_combined`,
  `docs_updater_phase`, `docs_updater_final`, `final_sweep`. Metered transports
  (`"api"`, `"p"`) remain available by explicitly setting a gate. (D001)
- **Plan Reviewer default model flipped Haiku → Opus** (`claude-opus-4-7`),
  matching the Opus-everywhere stance for this executor.
- **Autonomous failure ladder** (D003): retry once → auto-fallback to `"api"`
  for that single dispatch → on continued failure, record a
  `verification_gap` / `docs_gap` marker and continue the run, surfacing it in
  the Final Report. Never prompts the user.
- **Per-plan `verification_gaps` / `docs_gaps` fields** were added to state and
  surfaced prominently in the Final Summary Report.
- **Detach reconciliation** (D002): under `detach=true`, agent-default gates
  (not explicitly set) are rewritten to `"api"` with a one-line warning, so the
  subscription default never causes surprise metering on a headless parent.
  Explicit `"agent"` gates are respected (warn + proceed).

## Verification results

- [x] `python3 -m pytest scripts/ -q` → **153 passed** (152 baseline + 1 new
      `test_default_is_opus`).
- [x] Scaffold-split lint (`validate_scaffold_split.py`) → **OK** on all 4
      prompt files (docs-updater, plan-reviewer, verifier, transition); no
      scaffold drift.
- [x] `git diff --check` → clean (no whitespace errors).
- [x] Gate-value consistency sweep → all 7 gate sites carry an `"agent"` branch
      referencing `references/cross-cutting/agent-dispatch.md` (phase-0,
      phase-1, phase-transition, phase-2).

## Caveats

1. **`bun run check:legacy` fails — pre-existing and unrelated (verified).** The
   failure is limited to 6 `packages/orchestrator/*` Graphify-dependency flags.
   ZERO changed files are outside `skills/kws-claude-multi-agent-executor/`, and
   the identical 6 failures reproduce at base commit `e079bbc` (pre-run). This
   failure predates v2.25 and is not caused by it; resolving it is a separate
   Graphify-removal effort in an unrelated product tree, out of scope here.
2. **Eval-harness smoke — deterministic preflight RUN (PASS); live fixture loop
   DEFERRED.** The free, deterministic portion of `./evals/run.sh` was executed
   directly and passed: `compare_agentlens_events.py --self-test` (6 cases),
   `check_skill_contract.py` (all 46 contract checks), and
   `check_doc_freshness.py` (`passed: true`). Only the metered live-dispatch
   fixture loop remains deferred (requires credits / a manual attached session).

## Resolved during close-out

- **Stale `final_sweep` default note fixed** (`phase-2-finalization.md`): line 73
  still claimed the default was `"api"` in v2.22.0, contradicting the v2.25
  `"agent"` default documented immediately below — the MINOR finding from the
  Phase 2 batch Verifier. Corrected to state the v2.25 `"agent"` default with
  `"batch"`/`"api"` as opt-in transports.
- **decision-log ADR index gap fixed** (`docs/decision-log.md`): the cross index
  skipped from v2.22 to the cross-cutting section, leaving 5 ADRs unindexed (this
  run's v2.25 D001/D002/D003 + 2 pre-existing v2.23 ADRs). Added both sections;
  `check_doc_freshness.py` `decision_log_complete` now passes.

## Follow-ups

- Run a **live attached session** to validate real subscription-pool dispatch
  (every role in-session on the subscription with `$0` metered spend).
- Run the **eval baseline** (`./evals/run.sh`) live fixture loop to confirm no
  regression on the fixtures (deterministic preflight already green).
