# D001 — Quality-mode floor level

**Date**: 2026-05-13
**Status**: Decided (pending pilot empirical check)

## Context

Quality mode upgrades task treatment relative to balanced. Question:
where should the floor be — every task treated as MID minimum, every task
treated as HIGH minimum, or somewhere in between?

## Options considered

- **α — MID floor**: LOW → MID, MID stays MID, HIGH stays HIGH (+ best-of-N + Opus)
- **β — HIGH floor**: every task treated as HIGH, best-of-N everywhere
- **γ — User-controlled floor**: `mode=quality_strict` (HIGH floor) | `quality` (MID) | `balanced` | `fast`

## Analysis

The LOW tier in v2.6.0 enables: batch verifier (not per-task), SMALL effort
bucket (TDD skip allowed, ≤8 tool calls), parallel waves. All three are
**speed/cost optimizations**, not quality decisions. Quality mode should
remove these.

The HIGH tier extras (LARGE bucket, in proposed quality mode: best-of-N + Opus)
should remain reserved for tasks where **multiple reasonable implementations
exist**. Forcing every task to HIGH (β) means best-of-N runs on trivial
typo fixes — 3 candidates produce nearly-identical diffs and the judge picks
between noise.

Risk tier encodes **blast radius**, not **quality bar**. A typo fix has low
blast radius but still has a high quality bar (must not be wrong). Quality
mode raises the bar uniformly (TDD always, Verifier always); it does not
need to also escalate investment uniformly.

## Decision

**α (MID floor) as default** for `quality_alpha`.
**quality_plus** as the variant that additionally applies best-of-N to MID
tasks — to be validated empirically (pilot).

| Tier in plan | balanced (v2.6.0) | quality_alpha | quality_plus |
|--------------|-------------------|---------------|--------------|
| LOW | batch verifier, SMALL bucket | **MID floor** | **MID floor** |
| MID | per-task verifier, MEDIUM bucket | (same) | + best-of-3 + Opus |
| HIGH | per-task verifier, LARGE bucket | + best-of-3 + Opus | + best-of-3 + Opus |

## Open question to be answered by pilot

Does best-of-N add quality on MID tasks, or is `quality_plus` over-investment
that adds judge selection noise without correctness gain?

## Consequences

- `quality_alpha` and `balanced` produce **identical** runs on any plan that
  has no HIGH tasks. This is intentional but means `quality_alpha` requires
  a HIGH-bearing fixture to demonstrate value. See [D004](./D004-pilot-scope.md).
- Fixture 08 (both tasks MID) measures balanced vs quality_plus only.
