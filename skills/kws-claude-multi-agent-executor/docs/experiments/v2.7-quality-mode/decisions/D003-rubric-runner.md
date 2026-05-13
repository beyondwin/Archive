# D003 — Deterministic rubric runner replaces LLM correctness estimation

**Date**: 2026-05-13
**Status**: Implemented (commit d5aa5eb)

## Context

Calibration of the LLM judge (D002) revealed:
- Judge has per-rep variance on code-quality axis (std ±0.16)
- Judge gives fair partial credit, dampening mean deltas (16/20 vs 20/20 →
  0.7 vs 0.9, not 0.5 vs 1.0)
- Result: mean Δ = 0.10 between good and broken impls — below 0.2 advisor
  threshold

But the underlying truth is **deterministic**: 16 of 20 rubric checks
literally pass for `broken_impl`, 20 of 20 for `good_impl`. We were asking
an LLM to estimate a number that a shell loop can compute exactly.

## Decision

Add `evals/rubric.py`. For each fixture with an `expected.rubric` block,
run every `check:` shell command and report pass/fail counts.

Replaces the LLM's role for the **correctness axis** entirely. LLM judge
remains responsible for `code_quality` (subjective).

## Output format

```json
{
  "fixture": "<name>",
  "workdir": "<path>",
  "valid_inputs": {"passed": 10, "total": 10, "failures": []},
  "error_cases":  {"passed":  8, "total": 10, "failures": [{"desc": "...", "stderr": "..."}]},
  "summary":      {"total_passed": 18, "total_checks": 20, "pass_rate": 0.9}
}
```

## Verification

Run against calibration impls:

| Impl | valid_inputs | error_cases | **pass_rate** |
|------|--------------|-------------|---------------|
| good_impl | 10/10 | 10/10 | **1.00** |
| broken_impl | 10/10 | 6/10 | **0.80** |

**Δ = 0.20 deterministically.** Cleanly clears advisor's threshold with
zero variance.

## Trade-offs

- (+) Removes LLM stochasticity from the most important axis
- (+) Reusable across all current and future fixtures (not just 08)
- (+) Faster + cheaper than LLM (subprocess vs API call)
- (-) Requires fixture author to write rubric `check:` commands — small
  upfront cost per fixture
- (-) Cannot capture "spec violations that aren't in the rubric" — but those
  are by definition unspecified, so judging them objectively is suspect anyway

## Implementation notes

- YAML block scalars (`check: |`) for multi-line python `-c` invocations.
  Single-line escaped strings broke on `\n` literal handling.
- Exit code conventions: 0 = pass, 1 = wrong behavior (impl accepted invalid),
  2 = wrong exception type. Future analysis can distinguish.
- Need to update `evals/run.sh` to invoke `rubric.py` between `test_after`
  and the judge call. Pending.
