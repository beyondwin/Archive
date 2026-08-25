# D004 — Pilot scope: balanced vs quality_plus only

**Date**: 2026-05-13
**Status**: Decided

## Context

The plan called for a pilot comparing 3 modes (balanced / quality_alpha /
quality_plus) on fixture 08 with n=3 reps each = 9 runs.

But examination of fixture 08 revealed: both of its tasks are MID risk.
With D001's floor design, `quality_alpha` produces identical behavior to
`balanced` on plans with no HIGH tasks. There's no point running both —
they will produce the same outputs.

## Options

**A. Reduce pilot to 2 modes**:
- balanced × 3 + quality_plus × 3 = 6 runs (~$60–120)
- Tests: "does best-of-N + Opus on MID tasks beat standard Sonnet?"
- quality_alpha vs balanced comparison deferred to a fixture with HIGH tasks

**B. Upgrade fixture 08 Task 0 to HIGH**:
- Add wording like "load-bearing API across modules" to artificially elevate
- 3 modes × 3 reps = 9 runs (~$90–180)
- Pro: 3-way comparison as originally planned
- Con: artificial risk elevation — single-function API isn't truly HIGH

## Decision

**Option A**. Pilot = balanced vs quality_plus only.

## Rationale

1. Fixture 08 is **honest about its risk level**. A single new utility
   function is MID. Forcing HIGH is gaming the experiment.
2. quality_alpha's value proposition is "best-of-N on truly HIGH tasks
   (schema, API surface, cross-cutting)". Validate on a fixture that
   actually has such tasks — to be added in a later round if pilot
   justifies expansion.
3. Pilot's job is to produce a **first signal**. balanced vs quality_plus
   is the most informative comparison from fixture 08:
   - if quality_plus > balanced: best-of-N adds value to MID work → both
     alpha and plus are worth more investigation
   - if quality_plus ≈ balanced: best-of-N on MID is over-investment;
     alpha's MID-floor + HIGH-only best-of-N is the right design

## Consequences

- Pilot answers ONE question, not two. The second (quality_alpha vs
  balanced on HIGH tasks) requires a separate fixture, post-pilot.
- Pilot cost drops ~33% ($60–120 vs $90–180).
- If pilot result is borderline (Δ < 0.05 on rubric pass_rate), we need
  to either run more reps or design a more discriminating fixture before
  expanding scope.
