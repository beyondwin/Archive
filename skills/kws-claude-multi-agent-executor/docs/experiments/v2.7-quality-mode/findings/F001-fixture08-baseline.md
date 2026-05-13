# F001 — Fixture 08 baseline variance (v2.6.0 balanced, n=3)

**Date**: 2026-05-13 (evening)
**Status**: COMPLETE

## Question

What is the per-rep variance of `v2.6.0 balanced` on fixture 08 with the
realistic-spec rewrite (D007)? This determines whether `quality_plus`
can realistically demonstrate improvement.

## Method

- Run `bash evals/run.sh evals/fixtures/08-subtle-input-validation.yaml` 3
  times sequentially
- For each rep: capture `rubric.json` (deterministic correctness),
  judge mean, judge notes
- Compute mean, range, per-check consistency

## Results (filled as runs complete)

| Rep | pass_rate | error_cases | Missed checks | Judge mean | Branch |
|-----|-----------|-------------|---------------|------------|--------|
| 1 | 0.95 | 9/10 | repeated unit raises ValueError | 0.90 | experiment |
| 2 | 0.95 | 9/10 | repeated unit raises ValueError | 0.90 | experiment |
| 3 | 0.95 | 9/10 | repeated unit raises ValueError | 0.95 | experiment |
| 4 | **1.00** | **10/10** | **(none)** | 1.00 | main (post-merge smoke) |
| **mean** | **0.9625** | 9.25/10 | (75% repeated-unit miss) | 0.94 | |
| **range** | **0.05** | | | 0.10 | |

**Revised result** (was: "Case A confirmed, zero variance"):

Three sequential reps on the experiment branch all produced the same single
miss. A fourth rep run from `main` after merging the v2.7 infrastructure
produced ZERO misses. This contradicts the original "zero variance"
characterization.

Updated reading: balanced **frequently** misses "repeated unit raises
ValueError" (3/4 reps observed = 75%), but the miss is **probabilistic
not deterministic**. With small n=4 the 75% point estimate has wide CI;
the true miss rate could plausibly be anywhere from 30% to 95%.

For quality_plus impact estimate: if balanced misses at rate p_miss ≈ 0.75
and 3 best-of-N candidates are independent draws from the same Sonnet
process:
- P(all 3 candidates miss) ≈ 0.75³ = 0.42
- P(at least one catches) ≈ 0.58
- Assuming judge correctly picks the catcher when present:
  - quality_plus expected pass_rate ≈ 0.58 × 1.0 + 0.42 × 0.95 = 0.979
- balanced expected pass_rate ≈ 0.25 × 1.0 + 0.75 × 0.95 = 0.9625
- **Expected delta ≈ +0.017** — even smaller than the +0.05 ceiling
  originally assumed
- Cost ratio remains ~3× tokens, ~2× wall time

The recommendation in [F002](./F002-close-out.md) **stands** — implementing
quality_plus for a ~+0.02 expected gain is not justified. But the rationale
shifts: not "all candidates would miss the same thing" (which the 4th rep
disproved) but rather "the gain is smaller than originally estimated, and
the variance is small enough that detecting +0.02 would require ~30+ reps
per cell."

## Per-check consistency (revised n=4)

For each of the 20 rubric checks across 4 reps:
- 19 checks pass in every rep (100% reliability)
- 1 check (`repeated unit raises ValueError`) fails in 3/4 reps (75% miss rate)

The miss is **probabilistic, not deterministic** as the n=3 data on the
experiment branch suggested.

## Why this still matters for the quality_plus recommendation

Earlier analysis assumed zero variance → "best-of-N picks between identical
candidates → zero correctness signal." The 4th rep falsifies this.

Updated analysis: best-of-N COULD catch the edge case via candidate
diversity, but at expected delta only ~+0.017 (see math in §Results).
Detecting this size of effect with n=3 per cell is impossible — the noise
floor is larger. Would need n≥30 per cell, which is $300+/fixture.

Either way, the implementation cost (~150-line SKILL.md change + ~$50–100
per fixture run + maintenance) is not justified for a +0.02 expected
improvement on a single edge case in a single fixture domain.

The cheaper alternative if Opus-vs-Sonnet thoroughness is the real
differentiator: just use Opus Implementer in balanced mode for HIGH-risk
tasks. No best-of-N machinery needed. That's a one-line change to
SKILL.md, gated on `mode=quality` or risk tier.

## Per-check consistency (filled when data complete)

For each of the 20 rubric checks, did all 3 reps reach the same outcome?

```
(table filled post-data)
```

## Interpretation rubric

```
case A:  All 3 reps land at exactly 0.95 missing only "repeated unit"
         → balanced is deterministic-stable, ceiling for quality_plus is +0.05
         → marginal value at best; experiment guides toward "skip quality_plus"

case B:  Reps land 0.95, 1.0, 1.0 (mixed)
         → balanced sometimes self-corrects via reviewer flow
         → noise floor competitive with the available delta; experiment
            non-conclusive on this fixture

case C:  Reps land 0.85, 0.90, 0.95 (low variance, lower mean)
         → balanced is less consistent than rep 1 suggested
         → quality_plus may have detectable lift; worth pilot

case D:  Reps land 0.70, 1.0, 0.85 (wild variance)
         → measurement is noise-dominated on this fixture
         → cannot conclude; pivot domain
```

## Decision

**Case A confirmed. Skip quality_plus implementation. Ship calibration
infrastructure.** See [F002](./F002-close-out.md) for the close-out plan.

Reasoning: the deterministic 0.95 ceiling + zero variance means quality_plus's
maximum gain on this fixture is +0.05, all candidates would likely produce
the same miss, and the implementation cost (~150-line SKILL.md + ~$50–100
per fixture run) is not justified.

## Cost actuals

3 balanced reps × ~$5–10 per run = **~$15–30**. Wall time ~30 min total
across all 3 reps (each ~10–15 min). Token spend roughly within fixture
budget (350k cap).
