# D002 — Probe-fixture design: harness-contract adaptation + detect-then-fix (J2/J3)

**Date**: 2026-06-08
**Status**: Decided (implemented)

## Context

J2 (fixture 09, rubber-stamp / MAST FM-3.3) and J3 (fixture 10, error-propagation /
FM-2.3+3.2) both add "detect-then-fix" probes: a defect-prone task where the
existing tests pass but the spec requires uncovered behavior. The spec
(`품질개선-v2.30-구현-ko.md`) included illustrative fixture YAML.

Reading `evals/rubric.py` and `evals/run.sh` before writing revealed the spec YAML
did NOT match the real harness contract.

## Options considered

- **A — Copy the spec YAML verbatim.** Matches the written spec, but the fixtures
  would crash the harness (see Analysis) — a non-runnable fixture is worse than none.
- **B — Adapt to the real harness contract, preserve the spec's *intent*.** Keep
  the probe semantics (discount range rejection; money-rounding propagation) but
  conform to what `rubric.py`/`run.sh` actually parse.

## Analysis

Three concrete contract mismatches in the spec YAML:

1. **Rubric shape.** `rubric.py._run_section` calls `item.get("check")` on each
   item — items must be `{check:, desc:}` **dicts** under `valid_inputs` /
   `error_cases`. The spec used `happy_path:` with plain-string lists, which would
   raise `AttributeError` (str has no `.get`). → use `valid_inputs` + dict items.
2. **Bootstrap.** `run.sh` already runs `git init` + `git config` + the bootstrap
   (`bash -euxc`) + `git add -A && git commit "eval bootstrap"`. The spec bootstrap
   re-ran git init/config/commit → double-init. And `bootstrap` must be a `|` block
   string (all existing fixtures), not a YAML list. → strip git ops, use `|` string.
3. **Invocation.** `run.sh` always appends `plan=plan.md spec=spec.md mode=interactive`.
   The spec's `invocation: "plan=plan.md spec=spec.md"` would duplicate args. →
   `invocation: ""`.

Separately, an **arithmetic** correction: `round(2.675*100) == 268` (the float
lands at/above 267.5), so 2.675 does not discriminate naive-round from correct.
Replaced with `2.005` (→201), which discriminates both naive-round and
int-truncation. The error_cases boundaries (1.005→101, 2.005→201) plus the
propagation-sensitive aggregate (`total_cents([1.005,2.005])==302`) make the probe
catch both the latent defect and a sum-then-convert derailment.

**Detect-then-fix vs expected-halt.** These are NOT expected-halt fixtures
(`plan_review_should_flag: false`). The success criterion is that the *final
artifact* satisfies the deterministic `error_cases` rubric — i.e. the pipeline
caught the gap (Spec Coverage Walk or AC-shell Verifier) and fixed it before SHIP.
Both error_cases failing on the final artifact = silent rubber-stamp/propagation
ship = regression caught.

## Decision

**Option B.** Adapt both fixtures to the real harness contract; preserve probe
intent. Record the spec→harness divergence here so a future reader doesn't "fix"
the fixtures back to the (non-runnable) spec shape. Probe validity proven
deterministically before declaring done (F01).

## Consequences

- Fixtures 09/10 run under `./evals/run.sh fixtures/NN.yaml` and score via
  `rubric.py` with zero judge dependence on the deterministic axes.
- The spec doc's fixture YAML is now known-illustrative, not literal — noted in
  F01 and the JOURNAL.
- Fixture 09 is the measurement instrument for J8 (AC anti-rubber-stamp cross-check,
  D007).

## Open questions

- Whether to add a `mast_coverage`/rubric-shape linter so future probe fixtures
  can't drift from the `rubric.py` contract. Deferred (no drift incident yet).
