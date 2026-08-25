# D008 — J9 plan-DAG re-plan on SKIP deferred, record-only (P2)

**Date**: 2026-06-08
**Status**: Deferred (record-only) — no implementation, trigger recorded

## Context

When a task SKIPs (retry/verifier exhaustion, v2.29 I1), its dependent tasks get a
blanket-SKIP via dependency propagation. Some of those dependents might still be
runnable if the failed dependency were stubbed or the DAG re-arranged
(LLMCompiler Joiner / plan-and-execute re-plan patterns).

## Options considered

- **A — Automatic re-plan.** On SKIP, re-arrange the DAG / stub dependencies and
  continue. High regression risk + Goodhart concern (optimizing "tasks completed"
  can ship wrong work). Rejected this round.
- **B — Advisory-only first cut.** On SKIP, the orchestrator evaluates "could this
  dependent proceed with a stubbed dependency?" and surfaces it as an *advisory*
  (no automatic re-plan). Lower risk, but still adds orchestrator decision surface.
- **C — Record only.** Capture the design and the trigger; build nothing until a
  real incident shows blanket-SKIP is causing *excess* SKIPs.

## Analysis

Even the advisory cut (B) adds orchestrator behavior with no evidence it's needed —
we have no corpus incident showing blanket-SKIP over-propagates. Building it now is
speculative. The honest move is C: record the design and a concrete trigger so we
act on data, not intuition.

## Decision

**Option C.** No implementation. Trigger to revisit: an actual incident in the
`events.jsonl` / `run_report.json` corpus where blanket-SKIP caused excess SKIPs
(a dependent that demonstrably could have proceeded was skipped). When triggered,
adopt the narrow advisory cut (B) first — advisory before any automatic re-arrange,
and automatic re-plan only as a separate, fixture-eval-gated experiment.

## Consequences

- No runtime change. The dependency-propagation behavior (I1) is unchanged.
- A future re-plan effort has a recorded starting point and a data trigger.

## Open questions

- What metric cleanly identifies an "excess SKIP" in the corpus (distinguishing a
  correctly-propagated SKIP from an avoidable one). Define when the trigger fires.
