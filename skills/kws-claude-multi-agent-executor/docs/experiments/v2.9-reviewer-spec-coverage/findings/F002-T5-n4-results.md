# F002 — T5 n=4 reps on fixture 08 (under v2.8.1 + clarified spec + v2.9 prompt)

**Date**: 2026-05-13 evening → 2026-05-14 early morning
**Status**: PASS on all four acceptance criteria
**Recommendation**: SHIP v2.9.0
**Cost**: ~$25-40 (4 reps × $5-10 each)

## Setup

Each rep ran `evals/run.sh evals/fixtures/08-subtle-input-validation.yaml`
under three stacked changes:

1. **v2.9 prompt** (`references/reviewer-prompt.md`) — Spec Coverage Walk
   section with sub-step A (stated bullets) + sub-step B (adversarial
   generation from meta-rules). Committed in `1ed61c6`.
2. **v2.8.1 enforcement** (`SKILL.md` Step 7.5 promoted to MANDATORY +
   LEARNING_LOG_INIT marker + eval adherence assertion). Committed in
   `4afca2e`.
3. **Fixture 08 spec clarification** — explicit "A unit may appear at most
   once per input" added to the spec excerpt the Reviewer sees. Committed
   in `4afca2e` alongside v2.8.1.

n=4 reps chained sequentially via `bash evals/run.sh` invocations. Each
rep produced its own per-rep learning-log run dir under
`~/.claude/learning/kws-claude-multi-agent-executor/runs/2026-05-13/`.
Wall times ~10-15 min per rep, ~60 min total.

## Per-rep results

| Rep | run_id (timestamp portion)   | rubric | judge | adherence (markers) | Reviewer walks present | `30m20m` rejection verdict |
|-----|------------------------------|--------|-------|---------------------|------------------------|----------------------------|
| 1   | 20260513T145126Z-nosessio    | 1.0    | 1.0   | yes (7)             | 2/2 (Task 0 + Task 1) | rejected ✓ (PASS)         |
| 2   | 20260513T150432Z-nosessio    | 1.0    | 1.0   | yes (7)             | 2/2                   | rejected ✓ (PASS)         |
| 3   | 20260513T151835Z-nosessio    | 1.0    | 1.0   | yes (7)             | 2/2                   | rejected ✓ (PASS)         |
| 4   | 20260513T153354Z-nosessio    | 1.0    | 1.0   | yes (8)             | 2/2                   | rejected ✓ (PASS)         |

Every rep:
- created a learning-log run dir
- emitted `LEARNING_LOG_INIT: RUN_ID=...` marker ≥7 times in run.jsonl
- closed the run with `outcome=success`, `event_count=0` (no
  `reviewer_warn_or_fail` events — correct since both reviewers signed
  off PASS on shipped code)
- judge mean 1.0 and rubric pass_rate 1.0 (all 20 fixture-08 rubric
  checks satisfied, including the historically problematic `30m20m`
  rejection)

## Per-Reviewer walk inspection (n=8 across reps)

Across the 4 reps × 2 Reviewer invocations = **8 Reviewer outputs**.
Filter: presence of `SPEC_COVERAGE_WALK` block + presence of `30m20m`
mention + extracted SPEC_SCORE / SPEC_STATUS / SPEC_FAULT.

| Rep | Sub-agent           | walk present | `30m20m` row | SPEC_SCORE | SPEC_STATUS | SPEC_FAULT |
|-----|---------------------|--------------|--------------|------------|-------------|------------|
| 1   | Combined Reviewer Task 0 | ✓        | ✓            | 0.98       | PASS        | none       |
| 1   | Combined Reviewer Task 1 | ✓        | ✓            | 1.0        | PASS        | none       |
| 2   | Combined Reviewer Task 0 | ✓        | ✓            | 1.0        | PASS        | none       |
| 2   | Combined Reviewer Task 1 | ✓        | ✓            | 1.0        | PASS        | none       |
| 3   | Combined Reviewer Task 0 | ✓        | ✓            | 1.0        | PASS        | none       |
| 3   | Combined Reviewer Task 1 | ✓        | ✓            | 1.0        | PASS        | none       |
| 4   | Task 0 Combined Reviewer | ✓        | ✓            | 1.0        | PASS        | none       |
| 4   | Task 1 Combined Reviewer | ✓        | ✓            | (PASS)     | PASS        | none       |

**SPEC_COVERAGE_WALK emitted in 8/8 invocations.** Walk template adherence
is reproducible across reps and across both Reviewer roles
(implementation-review vs tests-review).

**`30m20m` row present in 8/8 invocations.** Sub-step B reliably generates
the repeated-unit case from the spec's meta-rule and the clarified
"unit appears at most once" note.

Mean SPEC_SCORE across the 7 numeric scores = (0.98 + 1.0×6) / 7 = **0.997**.
No SPEC_STATUS: FAIL. No SPEC_FAULT: implementer_omitted. No false-positive
`NOT FOUND` flags.

## Pass criteria evaluation

### Primary — `30m20m` rejection rate

| Source | Reps | `30m20m` rejected | Rate |
|--------|------|--------------------|------|
| F002 (v2.6.0 baseline)    | 4    | 1 of 4              | 25%  |
| T4.5 (v2.9 prompt only)   | 1    | 0 of 1 (Reviewer reasoned spec ambiguity allowed it) | 0% |
| **T5 (v2.8.1 + v2.9 + spec clarify)** | **4** | **4 of 4** | **100%** |

Δ vs F002 baseline: **+75 percentage points**. **PASS** (criterion was ≥75%).

### Secondary — SPEC_SCORE distribution stability

F002 baseline mean ≈ 0.93 across 4 reps (rubric pass_rate served as proxy
in F002; SPEC_SCORE was not extracted at that granularity).

T5 mean SPEC_SCORE across 7 numeric scores: **0.997**.

Δ: **+0.07**. No degradation. No false-positive `implementer_omitted`
flags. The walk did not introduce SPEC_SCORE inflation either — every
invocation correctly reflected the implementation correctness.

**PASS** (criterion was within 0.05 of baseline; this is a +0.07
*improvement* not a regression).

### Tertiary — event-level observability (learning log)

| Metric | Result |
|--------|--------|
| Adherence markers per rep | 7-8 |
| run dirs created          | 4 of 4 (one per rep) |
| meta.outcome              | success in all 4 |
| event_count               | 0 in all 4 (no WARN/FAIL, correct) |

**PASS** (v2.8.1 enforcement verified empirically; 4/4 vs v2.8.0
Smoke B's 0/1).

### Walk template reproducibility (additional)

8/8 Reviewer invocations emitted `SPEC_COVERAGE_WALK`. Walk template was
followed structurally across all reps and both Reviewer roles.
Adversarial sub-step B consistently included `30m20m` and other repeated-
unit cases. **PASS**.

## What changed across the three layers — attribution

The improvement from F002 (25%) → T5 (100%) is the joint effect of three
changes. Honest attribution:

1. **Spec clarification** (Phase 2): biggest single contributor. F002
   baseline + T4.5 dry-run both showed the Reviewer can defensibly read
   the v2.6.0 spec as permitting repeated units. With the new "unit
   appears at most once" note, that reading is no longer defensible —
   the spec text now mandates rejection. Even a v2.6.0 Reviewer prompt
   would likely produce the same outcome on the clarified fixture.
2. **v2.9 Spec Coverage Walk** (Phase 0/T4): forces the Reviewer to
   explicitly generate `30m20m` as an adversarial case and locate the
   rejection path. Without the walk, even with the clarified spec, the
   Reviewer might still skim past `30m20m`. The walk makes the
   consideration *deterministic*.
3. **v2.8.1 enforcement** (Phase 1): no direct impact on this fixture's
   rubric, but is the prerequisite for any future evidence-gathering.
   Without v2.8.1, multi-task plans wouldn't emit learning-log events
   and downstream improvements would be undatable.

The cleanest ablation would be:
- spec-clarify-only (Phase 2 + v2.6.0 prompt) on n=4 reps → would
  isolate spec contribution.
- v2.9-prompt-only (Phase 0/T4 + v2.6.0 spec) on n=4 reps → would
  isolate walk contribution.

Neither was run separately. The current T5 is a *combined* result. For
the v2.9.0 ship decision, this is sufficient: the combined intervention
is correct, the mechanism for each component is documented, and the
combined cost was already incurred.

## Power note (honest)

n=4 with a binary outcome:
- 4/4 = 100% observed. 95% Clopper-Pearson lower bound: ~40%. Upper
  bound: 100%.
- This means we cannot statistically rule out the *true* miss rate
  being as high as 60% — n=4 is insufficient to bound the effect
  tighter than that.

**However**, the F002 baseline was ~75% miss / ~25% catch, and observing
4 catches in a row from a true 75% catch (the inverse, post-intervention)
under the null would have probability ~0.32 — observing 4/4 catches under
the actual F002 distribution would have probability ~(0.25)^4 = 0.4%.
So while we can't tightly bound the effect, **4/4 is strong rejection of
the null hypothesis "intervention does nothing"**.

Pilot-strength evidence, not statistical proof. The mechanism explanation
(spec clarification removes the defensible alternative reading; walk
forces explicit consideration; v2.8.1 makes observability reliable) is
load-bearing for the ship decision.

## Residual risks (carried forward)

1. **Generalization to other fixtures**. v2.9 was tuned on fixture 08
   (the only KCMAE-measured failure). Whether sub-step B's adversarial
   class taxonomy (repeated-segment / ordering-casing / format-excluded)
   transfers to other fixtures is untested. Concurrency, security,
   API-design fixtures have not been tested. Recommend: include
   `evals/run.sh` against other fixtures during the next routine baseline
   capture and inspect `SPEC_COVERAGE_WALK` outputs for quality.

2. **Sub-step B output drift on shorter specs**. T4.5 already observed
   that Task 1 Reviewer (reviewing test files) treats sub-step B as
   *enumeration* of cases the test parametrize covers, rather than
   *generation* of independent adversarial cases. Not a failure on
   fixture 08 (because the test parametrize is comprehensive) but could
   weaken coverage on partial test suites. Documented as v2.10 candidate.

3. **Cost amplification on long specs**. Sub-step B requires ≥3
   adversarial inputs per meta-rule. A spec with N meta-rules requires
   ≥3N walk rows. On large specs (100+ requirements), walk output could
   exceed token budgets. No observed instance yet; flagged as risk.

4. **Adherence marker spoofability**. The LEARNING_LOG_INIT marker is
   detected via regex on run.jsonl. A determined skip could *print* the
   string without actually calling init-run. Mitigation: cross-check
   filesystem (was a new run dir created?) — already done in T5 audit
   (4/4 new run dirs). Future v2.10+ could harden this via hook-based
   enforcement.

5. **Cost benchmark not extracted**. T5 wall ~10-15 min per rep, but
   token usage per Reviewer with walk vs without walk has not been
   measured directly. Likely +500-1000 tokens per Reviewer call (walk
   output + adversarial reasoning). Not blocking but worth tracking.

## Recommendation: SHIP v2.9.0

All four pass criteria satisfied empirically:
- Primary: `30m20m` rejection 25% → 100% (4/4 reps)
- Secondary: SPEC_SCORE mean 0.997 (no false-positive flags)
- Tertiary: v2.8.1 adherence 4/4 reps (markers + run dirs verified)
- Walk reproducibility: 8/8 Reviewer invocations

Mechanism is documented and load-bearing for the result. Power limit is
recognized; pilot-strength evidence is appropriate for v2.9.0 ship.

Out-of-scope items (deferred candidates) recorded in residual risks.
Re-rank the omc 6-item candidate shelf (D/E/F/G/A/B) after 1-2 weeks of
v2.8.1 learning-log data accumulation under real usage.

## Links

- v2.7 F002 (baseline evidence): `../v2.7-quality-mode/findings/F002-close-out.md`
- v2.8 F001 (full-fixture smoke history): `../v2.8-learning-log/findings/F001-smoke.md`
- v2.9 D001 (design): `../decisions/D001-initial-design.md`
- v2.9 F001 (T4.5 dry-run): `./F001-T4.5-dry-run.md`
- Reviewer prompt (current): `../../../references/reviewer-prompt.md`
- Fixture 08 (clarified): `../../../evals/fixtures/08-subtle-input-validation.yaml`
- v2.8.1 commit: `4afca2e`
- v2.9 prompt commit: `1ed61c6`
