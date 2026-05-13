# F002 — v2.7 Quality Mode Experiment: Close-out

**Date**: 2026-05-13
**Status**: FINAL
**Outcome**: NEGATIVE on quality_plus hypothesis; POSITIVE on rubric infrastructure.

## TL;DR

We hypothesized that adding a `quality_plus` mode (best-of-3 Opus implementers
+ Opus judge for MID/HIGH tasks) would measurably improve output quality
over balanced v2.6.0. The baseline-variance probe on fixture 08 (realistic
input-validation MID task) shows:

- balanced v2.6.0 reliably reaches **0.95 rubric pass_rate** (19/20)
- The single consistent miss is `parse_duration("30m20m")` not raising
  ValueError — a "have I seen this unit?" judgment call
- The ceiling for quality_plus is **+0.05** (move from 0.95 → 1.0)
- Cost to implement quality_plus: ~150-line SKILL.md change (~2 hrs)
- Cost to run quality_plus per task: ~3× tokens, ~2× wall time

The marginal gain (0.05 across 1 in 4–5 specific edge categories) does not
justify the implementation surface area + per-run cost.

**Recommendation**: do NOT implement quality_plus. Ship the calibration
infrastructure (deterministic rubric runner + harness integration +
fixture 08) — these are independently valuable.

## What we built that ships

| Artifact | Purpose | Ship to `main`? |
|----------|---------|-----------------|
| `evals/rubric.py` | Deterministic correctness measurement | **Yes** |
| `evals/judge.md` (rubric-aware update) | Judge derives correctness from rubric.json | **Yes** |
| `evals/run.sh` (rubric integration) | Harness invokes rubric.py automatically | **Yes** |
| `evals/fixtures/08-subtle-input-validation.yaml` | Regression test for the "repeated unit" miss | **Yes** |
| `evals/calibration/` | Reference impls + judge calibration test runner | **Yes** |
| `docs/experiments/v2.7-quality-mode/` | The experiment record itself | **Yes** (as historical) |
| `references/best-of-n-judge-prompt.md` | Best-of-N judge template, unused | **No** (orphan; keep on branch) |
| `docs/experiments/.../decisions/D008-quality-plus-skill-changes.md` | Design we never built | **No** (stays on branch) |

## What we don't ship

- `quality_plus` mode itself — not built, not justified by data
- `quality_alpha` mode — its value depends on HIGH tasks, which the
  current experiment never tested; deferred to a future fixture
- `best-of-n-judge-prompt.md` — orphaned reference, kept on branch for
  future re-use if the experiment is revived

## What we learned

1. **v2.6.0 balanced + Combined Reviewer is closer to a solved problem on
   realistic MID input-validation tasks than the hypothesis assumed.**
   Sonnet's regex/grammar instinct rejects 3 of the 4 "naive miss"
   categories I predicted, without being told.
2. **LLM judges alone are unreliable for narrow-margin discrimination.**
   Sonnet judge mean Δ = 0.13 (FAIL), Opus clean = 0.10 (FAIL),
   Opus with docstring cue = 0.32 (PASS but contaminated). The fix is
   structural: deterministic measurement of mechanical axes via
   `rubric.py`, LLM judge only for subjective axes.
3. **Per-rep stability of the Sonnet implementer is higher than expected.**
   3/3 reps produced the exact same single miss (`30m20m`), suggesting
   the miss is a property of how Sonnet reads ambiguous specs, not a
   probabilistic outcome. This actually argues AGAINST best-of-N being
   useful: 3 candidates would likely all produce the same code with
   the same miss.
4. **Designing fixtures with deliberately omitted-from-spec edge cases is
   confirmation-bias-prone** (advisor #5). After D007 we deliberately
   stopped iterating fixture difficulty.
5. **Pilot-first scoping (D006) saved 1.5+ days of work.** The full
   experiment would have implemented quality_alpha + quality_plus +
   designed 4 fixtures + run 45 cells before discovering the marginal
   ceiling. Doing baseline-variance first surfaced the answer at $30.

## Per-rep data — final (n=4 including main post-merge smoke)

4 reps of balanced v2.6.0 on fixture 08:

| Rep | rubric pass_rate | Missed | Judge mean | Branch |
|-----|------------------|--------|------------|--------|
| 1 | 0.95 | "repeated unit raises ValueError" | 0.90 | experiment |
| 2 | 0.95 | "repeated unit raises ValueError" | 0.90 | experiment |
| 3 | 0.95 | "repeated unit raises ValueError" | 0.95 | experiment |
| 4 | **1.00** | **none** | **1.00** | main (smoke) |

- **mean**: 0.9625
- **Variance on rubric**: 3/4 reps missed, 1/4 caught — **probabilistic, ~75% miss rate**
- **Updated quality_plus expected gain**: ~+0.017 (best-of-3 with 75% miss rate per candidate)

The rep 4 result was an unexpected finding from the post-merge smoke test
on main. It revealed that the "zero variance" claim from the n=3 data was
premature. Recommendation stands but rationale revised — see
[F001](./F001-fixture08-baseline.md) for full analysis.

## A cheaper alternative not pursued

If the 75% miss rate is driven by Sonnet's thoroughness rather than candidate
diversity, the simpler intervention is to **escalate the Implementer to Opus
on HIGH-risk tasks** without any best-of-N machinery. Single Implementer,
Opus model, ~2× cost (one Opus call instead of one Sonnet call), no
sub-worktree complexity, no judge needed.

This is a ~10-line change to SKILL.md Phase 1 Step 1 dispatch logic. Worth
considering as a future minor revision IF a real failure case justifies
investigation. Not pursued in this experiment because the 75% miss rate
was only discovered post-merge.

## When to revisit

quality_plus might be revisited if:
- A future fixture domain (concurrency, security semantics, API design
  judgment) shows balanced v2.6.0 reliably leaves >15% of rubric checks
  unsatisfied, AND
- Per-rep variance is low enough that quality_plus's hypothetical
  improvement is detectable with n≤5 reps

Until then: stop investing in this hypothesis. The data has spoken.

## Cost tally

| Phase | Cost | Notes |
|-------|------|-------|
| Calibration journey (Sonnet judge × 3 + Opus × 6) | ~$18 | Found judge alone is inadequate; pivoted to rubric.py |
| Ceiling check (balanced × 3 reps) | ~$30 | Baseline variance: 0.95 reliably |
| Documentation + design | ~$0 | Local work |
| **Total spent** | **~$48** | Vs. authorized $300–900 |

| Spending NOT incurred | Reason |
|-----------------------|--------|
| quality_plus implementation (~$0 in API but ~2 hrs) | Skipped — ceiling makes it marginal |
| Full pilot (6 runs) | Skipped — ceiling makes lift undetectable |
| Fixtures 09–11 design + runs (~$300+) | Pivoted to single-fixture deep-dive |
