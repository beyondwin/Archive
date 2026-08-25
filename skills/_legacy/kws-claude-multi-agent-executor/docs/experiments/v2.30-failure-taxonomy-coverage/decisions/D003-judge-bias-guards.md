# D003 — Judge bias guards scoped to the subjective axis only (J4)

**Date**: 2026-06-08
**Status**: Decided (implemented)

## Context

LLM-as-judge has well-documented pathologies: verbosity bias (longer = better),
position bias, self-preference. `evals/judge.md` had no explicit guard against
these. This affects eval *trust*, especially the subjective `code_quality` axis.
The deterministic axes (`correctness`, `spec_compliance`) are already derived
mechanically from `rubric_results` (`summary.pass_rate`, `error_cases.passed/total`).

## Options considered

- **A — No change.** Accept judge variance. Cheapest, but a known bias source
  remains uncorrected and the eval's code_quality signal stays noisy.
- **B — Add bias guards across all axes.** Risk: re-touching the deterministic
  axes invites re-estimation from the diff, undoing the rubric-authority invariant.
- **C — Add bias guards scoped to the subjective axis only.** Deterministic axes
  stay mechanical and are explicitly excluded.

## Analysis

The deterministic axes are already the strongest part of the eval — their value is
precisely that they do NOT depend on judge judgment. Any wording that invites the
judge to "reconsider" them is a regression. The bias risk lives entirely in
`code_quality`. So the guard belongs there and nowhere else. The main hazard of the
guard itself is over-correction: "verbosity ≠ quality / minimal sufficiency is
near-perfect" could make the judge *under*-value a concise-but-complete `good_impl`,
shrinking the calibration delta.

## Decision

**Option C.** Add a **Bias guards** section before "Score each axis", scoped to
`code_quality`, plus one line on the code_quality axis ("minimal sufficiency is
near-perfect — code volume is independent of score"). Restate (do not change) the
deterministic-axis mechanical rule inside the guard so the exclusion is explicit.
Add a regression check to `evals/calibration/README.md`:
`score(good_impl) − score(broken_impl) ≥ 0.2` must still hold across 3 reps after
the edit; if it drops, the guards over-corrected → soften/revert, do not ship.

## Consequences

- code_quality scoring is bias-hardened; deterministic axes unchanged → no
  ARCHITECTURE §8 trigger (the scoring axes themselves are unchanged).
- The calibration re-run is a paid step, gated to "once per judge change" — it is
  part of the SHIP gate, not run in this in-session pass.

## Open questions

- Whether the calibration `good_impl`/`broken_impl` pair is sensitive enough to
  detect a small over-correction (Δ shrink from 0.2→0.15). If not, may need a
  concise-impl-specific calibration case. Revisit if the paid re-run is ambiguous.
