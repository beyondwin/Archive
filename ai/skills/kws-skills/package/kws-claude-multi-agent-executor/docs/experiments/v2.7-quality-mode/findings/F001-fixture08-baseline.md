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

| Rep | pass_rate | error_cases | Missed checks | Judge mean |
|-----|-----------|-------------|---------------|------------|
| 1 | 0.95 | 9/10 | repeated unit raises ValueError | 0.90 |
| 2 | 0.95 | 9/10 | repeated unit raises ValueError | 0.90 |
| 3 | 0.95 | 9/10 | repeated unit raises ValueError | 0.95 |
| **mean** | **0.95** | 9/10 | (always same) | 0.917 |
| **range** | **0.00** | 0 | n/a | 0.05 |

**Result**: Case A confirmed. All 3 reps produced identical rubric outcomes
— same exact pass_rate, same single missed check, zero variance on the
deterministic measurement. Judge mean varied slightly (0.90 / 0.90 / 0.95)
because the LLM judge's `code_quality` axis has its known stochasticity.

## Per-check consistency

For each of the 20 rubric checks, all 3 reps produced the same outcome:
- 19 checks pass in every rep
- 1 check (`repeated unit raises ValueError`) fails in every rep

Zero variance on outcome. Sonnet's behavior on this fixture is
**reproducibly deterministic** at the level of rubric pass/fail.

## Why this matters for quality_plus

Best-of-N's value proposition rests on **selecting between diverse
candidates**. If 3 Opus candidates would also reliably produce the same
miss (because Sonnet did 3/3 times, and the miss is in Sonnet's spec
interpretation, not its sampling), best-of-N picks between identical
candidates and adds zero correctness signal.

Best-of-N could still help if Opus is MORE thorough than Sonnet on this
class of edge case — but that would be measuring "Opus vs Sonnet
Implementer", not "1 vs N candidates". A cheaper experiment is just
"use Opus Implementer in balanced mode" — no best-of-N machinery needed.

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
