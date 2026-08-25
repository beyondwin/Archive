# D001 — Metric is prevention (first-pass + retries), not final quality

**Date**: 2026-06-02
**Status**: Decided

## Context

The intervention adds an adversarial meta-rule self-check to the Implementer
prompt, targeting the `30m20m`-class miss measured in v2.7 F002 (~75% first-pass
miss on fixture 08). The natural instinct is to measure success as "fixture 08
rubric pass-rate goes up."

But v2.9 (Reviewer Spec Coverage Walk) already shipped and its F002 close-out
recorded 4/4 reps at rubric 1.0 on fixture 08. The reviewer walk catches the
`30m20m` miss and forces a reset + re-dispatch; by end-of-run the artifact is
correct. The *final* rubric pass-rate on this fixture is therefore already at
ceiling, independent of any Implementer change.

## Options considered

- **A — Measure final rubric pass-rate (full orchestrator run).** Familiar metric,
  reuses `evals/run.sh`. But on fixture 08 it is pinned at ~1.0 by the v2.9 walk, so
  the Implementer change would register as a null effect even if it works perfectly.
- **B — Measure first-pass (pre-review) pass-rate + review-retry count.** Captures
  the actual mechanism of the intervention (prevention before detection). Requires
  isolating the Implementer's first output (see D002).
- **C — Measure end-to-end wall-time / token cost.** The downstream consequence of
  fewer retries. Real but noisy on a single fixture; better as a secondary signal.

## Analysis

The intervention's theory of value is *prevention*: catch the adversarial input at
creation so the reviewer never has to bounce it. That theory is invisible to metric
A (ceilinged) and only directly visible to metric B. Metric C is the eventual payoff
but too noisy to be primary at n≈4.

Consequence of this framing: if the reviewer walk reliably catches the miss in one
cheap retry, the prevention saving may be too small to justify the prompt surface —
exactly the v2.7 D008 "designed but not shipped" pattern. We accept that a SKIP is a
legitimate, expected-possible outcome, not a failure of the experiment.

## Decision

Primary metric = **first-pass rejection rate on the 4 meta-rule-only fixture-08
checks** (`30m20m`, `1h 30m`, `1H`, `s`). Secondary = total first-pass rubric
pass-rate (regression guard) and `ADVERSARIAL_SELFCHECK:` adherence. Final
rubric pass-rate is explicitly NOT a success criterion (it is pinned by v2.9).

## Consequences

- Enables: a clean read on whether the Implementer change prevents the miss,
  uncontaminated by the reviewer walk.
- Commits: building an isolated Implementer measurement (D002) rather than reusing
  `evals/run.sh` as-is.
- Blocks nothing.

## Open questions

- Threshold for "worth shipping" on cost saving alone is not yet pinned; deferred to
  the findings doc once first-pass numbers are in.
