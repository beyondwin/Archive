# D002 — Judge model choice (Sonnet vs Opus)

**Date**: 2026-05-13
**Status**: Decided (Opus for experiment; rubric.py for correctness axis — see D003)

## Context

The `evals/judge.md` template was written for Sonnet (per existing v2.6.0
infrastructure). For the v2.7 experiment, the judge is the sole measurement
instrument — its reliability gates the experiment.

## Calibration results

Tested both with the same `good_impl` (handles all 20 rubric checks) and
`broken_impl` (silently accepts 4 invalid inputs that the spec requires to
raise ValueError).

| Judge | Cue removed | mean Δ | Verdict |
|-------|-------------|--------|---------|
| Sonnet | n/a | +0.13 | FAIL ≥0.2 |
| Opus | with docstring cue | +0.32 | PASS but contaminated |
| Opus | docstring cue removed | +0.10 | FAIL — partial credit + variance |

Findings:
- Sonnet judge has high per-axis noise; mean diluted by cost_efficiency
  artifact (both 1.0) and spec_compliance staying at 0.4 for both impls
- Opus judge correctly identifies all 4 bugs in `notes` but assigns
  proportional partial credit (16/20 → 0.7, 20/20 → 0.9) — fair but small
  delta
- Opus has high per-rep variance on `code_quality` (std ±0.16 on good_impl)

## Decision

For the v2.7 experiment:
- **LLM judge model**: Opus (`claude -p --model opus`). Sonnet judge does
  not reliably hit the 0.2 threshold even directionally.
- **Use of judge**: judge is responsible only for the subjective
  `code_quality` axis going forward. Correctness is measured deterministically
  via [D003](./D003-rubric-runner.md).

## Cost implication

Opus judge × N candidates is more expensive than Sonnet. For best-of-3 +
final composite judge per task, ~$15–20 in judge calls per fixture run vs
~$3 for Sonnet. Within experiment budget.

## Alternatives rejected

- **Sonnet judge with more reps (n=10)**: would average out variance but
  doesn't fix the partial-credit issue and costs more in aggregate than
  Opus × 3.
- **Sonnet judge + improved prompt**: prompt-engineering iteration without
  obvious converge point; deferred.
