# F01 — Probe validity for fixtures 09 / 10 (deterministic, no LLM)

**Date**: 2026-06-08
**Status**: FINAL (for the deterministic probe-validity question; SHIP eval separate)

## Question

Plan §5 names the top risk for J2/J3: *"the probe fixture is inert — even with the
defect planted, the rubric passes."* Before spending any paid eval, can we prove
deterministically that fixtures 09/10 actually discriminate a defective
implementation from a correct one?

## Method

For each fixture, seed two implementations in throwaway workdirs and run the real
`evals/rubric.py` against each (no skill, no judge, no API):

- **09 broken** — `apply_discount` without range validation (the bootstrap default).
- **09 good** — `apply_discount` that raises ValueError for pct outside 0..100.
- **10 broken** — naive `round(amount*100)` `to_cents` + a `total_cents` that sums
  it (defect propagates).
- **10 good** — `decimal.Decimal` + `ROUND_HALF_UP` `to_cents` + per-item `total_cents`.

Raw `rubric.py` output is committed alongside this finding:
`rubric-09-broken.json`, `rubric-09-good.json`, `rubric-10-broken.json`,
`rubric-10-good.json`.

## Results

| Fixture | Impl | valid_inputs | error_cases | pass_rate |
|---------|------|--------------|-------------|-----------|
| 09 spec-intent-uncovered | broken | 3/3 | **0/2** | 0.6 |
| 09 spec-intent-uncovered | good | 3/3 | 2/2 | **1.0** |
| 10 error-propagation | broken | **2/3** | **0/2** | 0.4 |
| 10 error-propagation | good | 3/3 | 2/2 | **1.0** |

Discrimination (good − broken pass_rate): **09 = 0.4**, **10 = 0.6**.

For fixture 10, the broken impl fails BOTH error_cases (to_cents 1.005→100≠101,
2.005→200≠201) AND the propagation-sensitive aggregate
(`total_cents([1.005,2.005])` = 100+200 = 300 ≠ 302). The whole-dollar valid_inputs
(300, 100) pass for both impls, as designed (non-discriminating controls).

## Interpretation

Both probes are valid: a planted defect drives the deterministic `error_cases`
(and, for 10, the aggregate) to fail, while a correct implementation scores 1.0.
`spec_compliance` in the judge is `error_cases.passed/total`, so a silent
rubber-stamp / propagation lands as `spec_compliance = 0.0` — directly visible.

This does NOT mean the *pipeline* catches the defect — that is what the paid eval
measures (does the Combined Reviewer Spec Walk / AC-shell Verifier surface it and
fix it before SHIP). F01 only establishes that the **measurement instrument works**:
if the pipeline rubber-stamps, the fixture will register it as a regression rather
than passing blindly.

It also confirms the fixtures conform to the real `rubric.py` contract
(`valid_inputs`/`error_cases` as `{check:,desc:}` dicts), validating the D002
harness-contract adaptation away from the spec's illustrative YAML.

## Decision

Probe validity PASS for both fixtures. Proceed to the paid eval (1-rep pilot → n=4)
as the SHIP gate in a later pass — out of scope for this single in-session run.

## Cost actuals

$0 — deterministic `rubric.py` only, no model calls. Wall time ~seconds.
