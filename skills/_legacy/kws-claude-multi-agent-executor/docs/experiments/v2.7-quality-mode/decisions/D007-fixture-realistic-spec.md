# D007 — Fixture 08 redesign: realistic underspec, keep full rubric

**Date**: 2026-05-13 (evening)
**Status**: Decided

## What happened

Ceiling check (Task #4) on fixture 08 with v2.6.0 balanced mode produced:

```
rubric pass_rate: 1.0
```

Sonnet, given an explicitly-enumerated spec listing all 15 edge cases,
handles all of them. There is no remaining room for quality_plus to
demonstrate improvement on this fixture.

## Root cause

The original fixture 08 `spec.md` enumerated every edge case explicitly:
- "9. Repeated unit (same unit appearing more than once): parse_duration('30m20m')..."
- "12. Internal whitespace: parse_duration('1h 30m')..."
- "13. Uppercase units: parse_duration('1H')..."
- etc.

This makes the fixture a **reading comprehension test**, not an
implementation-quality test. Sonnet reads the bullet list and adds matching
ValueError checks. No room for "would a thoughtful implementer have caught
this even without being told?"

This is the **opposite** of the realistic scenario the experiment was meant
to measure: a busy spec author writes the happy path + obvious errors and
implicitly relies on the implementer's judgment for the rest.

## Decision

Rewrite fixture 08 `spec` block:
- **Keep**: happy-path examples, the most obvious error cases (empty, bare
  number, unknown unit, negative, decimal). These are what any spec would
  realistically mention.
- **Remove from spec, keep in rubric**: the 4 "naive miss" categories —
  internal whitespace, uppercase units, repeated unit, unit without integer.
  A thoughtful implementer should validate these even without being told,
  because they're natural consequences of "validate input strictly."

## Why this isn't gaming the experiment

This concern (advisor #5: confirmation bias) deserves a direct answer.

The fixture is gameable if I designed it to fail Sonnet AND succeed
quality_plus by construction. But:

1. The 4 omitted cases are not obscure (Unicode digits, hex prefix, etc) —
   they are basic input validation that a careful developer mentions in
   review.
2. Whether balanced misses any of them is unknown until measured. Could be
   0/4, could be all 4. Either result is informative.
3. The rubric is **specification of what good means** — it doesn't change
   between modes. quality_plus and balanced are measured against the same
   bar.
4. If quality_plus does no better than balanced on this fixture, the
   experiment correctly returns negative.

The honest framing: this measures "when spec leaves room for judgment, does
best-of-N + judge select implementations with better judgment?"

## What stays

- Fixture name, file structure, task plan (2 tasks: implement + tests)
- Rubric (20 deterministic checks unchanged)
- Bootstrap (Python project setup)
- Expected outcomes

## What changes

- Spec body — see fixture 08 commit on this branch for the diff
- README in fixture 08's bootstrap doesn't claim "all edges are listed"

## Re-run plan

After fixture redesign:
1. Re-run balanced × 1 on fixture 08 (ceiling re-check)
2. If pass_rate ≥ 0.90: still too easy, redesign harder (consider removing
   more from spec, or fall back to a different domain)
3. If pass_rate in 0.70–0.85: ideal — room for quality_plus to improve
4. If pass_rate < 0.70: balanced is missing too much; fixture is realistic;
   proceed with confidence

Budget for this iteration: ~$10 per balanced ceiling re-run. Affordable.
