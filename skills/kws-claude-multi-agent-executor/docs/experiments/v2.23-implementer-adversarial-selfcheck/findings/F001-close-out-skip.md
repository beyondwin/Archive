# F001 — Close-out: SKIP (baseline defect no longer reproduces)

**Date**: 2026-06-02
**Outcome**: **SKIP** — do not ship the Implementer adversarial self-check.
**Disposition**: intervention reverted from the working tree; experiment record kept.

## Decision in one line

The defect this intervention prevents (v2.7 F002: ~25% first-pass rejection of
`30m20m`-class adversarial inputs on fixture 08) **no longer reproduces** on the
current Sonnet. Control already ceilings, so the intervention has no measurable
headroom to capture. Same disposition class as v2.7's best-of-N.

## Evidence

Isolated Implementer dispatch on fixture 08 Task 0 (`parse_duration`), scored
first-pass `src/duration.py` against the 20-check fixture-08 rubric, focusing on
the 4 meta-rule-only checks (`30m20m`, `1h 30m`, `1H`, `s`). Per D002, dispatch
model pinned to **Sonnet** (CLI 2.1.145). The reviewer walk (v2.9) is NOT in the
loop — this is pure first-pass prevention measurement.

| Arm | Model | n | Meta-rule first-pass | Total rubric | SELFCHECK line |
|-----|-------|---|----------------------|--------------|----------------|
| control   | Sonnet | 4 | **16/16 = 100%** | 4/4 reps at 20/20 | absent (correct) |
| treatment | Sonnet | 1 (pilot) | 4/4 = 100% | 20/20 | present + well-formed |

Hypothesis predicted control ≈ 25% (v2.7 F002: 1/4). Observed control = 100%
across 4 independent reps. **The premise is falsified on the current model.**

### Invalid first pilot (recorded for honesty)

The first pilot ran on the user's default model `claude-opus-4-8` because
`_run_implementer` omitted `--model`. Both arms ceilinged (expected on Opus). That
run is discarded; the bug is fixed (`--model sonnet` pinned) and the table above
is the Sonnet re-run. See JOURNAL T3.

## Why this is a SKIP, not a marginal-gain ship

Pass criteria (README) required ALL of:
1. Treatment meta-rule pass-rate ≥ 75% **vs ~25% control** — **fails**: control is
   already 100%, so there is no gap to close and no contrast to measure.
2. No regression on the 16 non-adversarial checks — moot (both at ceiling).
3. `ADVERSARIAL_SELFCHECK:` present and non-fabricated in ≥ N−1 reps — **met** in
   the pilot (line fired correctly, listing genuinely-generated adversarial
   inputs), but irrelevant given #1 fails.
4. No code-quality regression — not reached.

Criterion #1 is structurally unsatisfiable: you cannot raise a number that is
already at ceiling. Shipping would add permanent prompt surface (one instruction +
one output line in every Implementer dispatch) for zero measured benefit on the
current model — the exact anti-pattern the project's Goodhart guard exists to
reject, and the same call made in v2.7 D008 (best-of-N kept off main).

## Mechanism note (the one positive)

The intervention itself *works as designed*: in both treatment reps the
`ADVERSARIAL_SELFCHECK:` line enumerated real spec meta-rules ("strict grammar
validation", "unit may appear at most once") and listed genuinely-generated
adversarial inputs (`30m20m`, `1h1h`, `2d2d`, `1H`, `30M`, `1h 30m`, `s`, …),
confirmed via the verification-command fallback (test files out of scope on this
task). So this is not a "mechanism broken" null — it is a "problem already solved
by the model" null. If a future model regresses on adversarial-input strictness,
this intervention is a validated, ready-to-revive lever.

## Recommendation

- **Do not ship.** Leave v2.22 as production baseline.
- **Revert** `references/implementer-prompt.md` to HEAD (done — intervention was
  working-tree-only, never committed).
- **Keep** this experiment directory as the negative-result record and a
  ready-to-revive intervention + harness if a future Sonnet regresses.
- **Re-test trigger**: re-run `bench/run_ab.py --arm control` against fixture 08
  on any future Sonnet bump; if control meta-rule pass-rate drops below ~75%,
  revive the treatment arm and re-evaluate.

## Cost

6 Sonnet Implementer dispatches total (2 invalid Opus pilots discarded + 2 Sonnet
pilots + 4-rep Sonnet control baseline; the discarded Opus runs were 2 additional
dispatches). No full orchestrator runs ($5–15 each) were spent — the isolation
design (D002) kept the negative result cheap, as intended.
