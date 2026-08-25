# D001 — Hold Reviewer and Verifier on Sonnet (judge consistency)

**Status**: Accepted
**Date**: 2026-05-16

## Context

The experiment varies the Implementer model (Sonnet vs Opus). The Combined Reviewer's output (`spec_score`, `quality_score`, `review_tier`) is the primary quality signal. The Verifier's PASS/FAIL is the secondary signal.

If we let the Reviewer/Verifier model float with the Implementer, we conflate "did Opus implement better code?" with "did Opus-judge score the same code higher than Sonnet-judge would?" These are different questions and they bias in opposite directions — Opus judges tend to be more rigorous in spec checks (smaller positive bias on quality, larger negative bias on missed-spec-detail issues).

## Decision

Reviewer = Sonnet, Verifier = Sonnet. Fixed across both arms.

The Implementer is the only knob.

## Consequences

- Quality deltas reported are attributable to the Implementer model alone.
- We cannot make claims about the full "fully-Opus pipeline" from this experiment — that requires a separate run.
- If a future experiment varies the Reviewer too, that's its own ADR (likely v2.13).

## Alternatives considered

- **Vary all sub-agents to Opus together.** Rejected — conflates two effects and hides which one matters.
- **Use a third model (Haiku) as judge for neutrality.** Rejected — Haiku scoring isn't calibrated against the P4 quality thresholds; would invalidate `review_tier` comparison against historical runs.
