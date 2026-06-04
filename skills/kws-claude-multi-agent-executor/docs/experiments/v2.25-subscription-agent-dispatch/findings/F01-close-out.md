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

1. **`bun run check:legacy` fails — pre-existing and unrelated.** The failure is
   limited to `packages/orchestrator/*` Graphify-dependency flags. ZERO of the
   11 changed files are outside
   `skills/kws-claude-multi-agent-executor/`, so this failure predates v2.25 and
   is not caused by it.
2. **Eval-harness smoke (`./evals/run.sh`) DEFERRED.** It requires live dispatch
   and credits; to be run in a manual attached session.

## Follow-ups

- Run a **live attached session** to validate real subscription-pool dispatch
  (every role in-session on the subscription with `$0` metered spend).
- Run the **eval baseline** (`./evals/run.sh`) to confirm no regression on the
  fixtures.
