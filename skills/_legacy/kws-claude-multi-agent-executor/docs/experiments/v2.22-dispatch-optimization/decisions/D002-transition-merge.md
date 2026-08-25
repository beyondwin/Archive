# D002 — Transition T1 + T2 merge into a single dispatch

**Date**: 2026-05-31
**Status**: Decided (shipped, Phase A2)

## Context

Each Phase Transition ran two co-located sub-agent dispatches back to back:
- **T1** — the LOW-risk batch verification pre-filter (route docs-only tasks to
  lint, everything else to test).
- **T2** — the Combined Reviewer pass over the wave's work.

They share the same transition context (the just-completed wave's task set,
files, and state slice). Dispatching them separately pays the round-trip and
context-load cost twice for what is effectively one transition decision.

## Options considered

- **A**: Keep T1 and T2 as separate dispatches.
- **B**: Merge T1 + T2 into one combined dispatch (`transition_combined`) that
  returns both the pre-filter routing and the review verdicts.

## Analysis

The only real risk in merging is a semantic change to either output — e.g., the
batch pre-filter mis-routing or the reviewer's scoring drifting because the two
concerns now share a prompt. That is a parity question, so it gates on an
explicit before/after eval rather than on inspection alone.

## Decision

Merge T1 and T2 into a single `transition_combined` dispatch. A
**transition-merge parity eval** confirms the merged dispatch produces the same
routing and the same review verdicts as the two-dispatch path.

## Consequences

- One fewer round trip per Phase Transition; lower context load per transition.
- Cost attribution needs to split across roles — handled by the A3
  `combined_roles` cost-ledger field.
- The merged role becomes one of the API-direct roles in Phase B (D003).
