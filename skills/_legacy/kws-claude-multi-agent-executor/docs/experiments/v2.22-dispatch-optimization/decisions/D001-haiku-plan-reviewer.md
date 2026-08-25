# D001 — Plan Reviewer migrates to Haiku 4.5

**Date**: 2026-05-31
**Status**: Decided (shipped, Phase A1)

## Context

The Phase 0 Step 6.5 Plan Reviewer is a *mechanical* preflight audit: it checks
Files blocks, header levels, spec-manifest references, and resource-key
collisions against deterministic rubric items. It ran on Sonnet, the same tier
as the substantive Combined Reviewer, even though its job is closer to a linter
than a judgment call. That is unnecessary cost on the critical boot path.

## Options considered

- **A**: Keep Plan Reviewer on Sonnet (status quo).
- **B**: Migrate Plan Reviewer to Haiku 4.5.
- **C**: Drop the LLM Plan Reviewer entirely and rely on `check_skill_contract`
  / structural validators.

## Analysis

Option C goes too far — the rubric items include semantic checks (spec-manifest
ref validity, ambiguous Files globs) that the deterministic validators do not
cover. Between A and B, the open risk is whether Haiku agrees with Sonnet on the
rubric verdicts often enough. That is measurable, so it gates the migration on a
real agreement eval rather than on intuition.

## Decision

Migrate the Plan Reviewer to **Haiku 4.5**, backed by the
`plan-reviewer-rubric` eval (Haiku vs Sonnet agreement). The substantive
Combined Reviewer and Verifier stay on their existing tiers — only the
mechanical preflight moves down.

## Consequences

- Cheaper, faster boot-path audit; one fewer Sonnet dispatch per run.
- Establishes the pattern that *mechanical* roles ride the cheapest tier that
  preserves verdict parity, distinct from judgment roles.
- Ties future re-tier decisions to the agreement eval, not to feel.
