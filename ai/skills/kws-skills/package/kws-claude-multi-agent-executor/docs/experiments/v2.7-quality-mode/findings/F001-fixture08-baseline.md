# F001 — Fixture 08 baseline variance (v2.6.0 balanced, n=3)

**Date**: 2026-05-13 (evening)
**Status**: Data collection in progress (rep 1 done, reps 2–3 running)

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

| Rep | pass_rate | error_cases | Missed checks | Judge mean |
|-----|-----------|-------------|---------------|------------|
| 1 | 0.95 | 9/10 | repeated unit raises ValueError | 0.9 |
| 2 | 0.95 | 9/10 | repeated unit raises ValueError | 0.9 |
| 3 | ⏳ | | | |
| **mean** | (pending) | | | |
| **range** | (pending) | | | |

**Note**: Reps 1 and 2 produced **identical** rubric outcomes — same single
missed check, same pass rate. This is strong early signal for Case A
(deterministic-stable balanced behavior).

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

## Decision (filled after analysis)

(will be one of: ship quality_plus / skip quality_plus / pivot to different
fixture domain / accept null result)

## Cost actuals

(filled with token counts and wall times across all 3 reps)
