# Plan: kws-claude-multi-agent-executor v2.9 — Reviewer Spec-Coverage Walk

**Date**: 2026-05-13
**Owner**: kws
**Spec**: `docs/superpowers/specs/2026-05-13-kws-claude-multi-agent-executor-v2.9-reviewer-spec-coverage-design.md`
**Branch**: commit directly onto `codex/executor-learning-log` (where v2.8
lives, not yet merged to `main`), following v2.8's pattern of "branch shared,
file paths isolated". Only Claude executor files + the v2.9 spec/plan under
`docs/superpowers/` are staged; the user's parallel Codex executor work on
the same branch is left untouched. If v2.8 merges to `main` before v2.9
starts T4, rebase v2.9 commits onto `main`.

## Architecture summary

Single change to `references/reviewer-prompt.md`: insert a strict-template
"Spec Coverage Walk" section between the Skill-invocation paragraph and
Part 1, requiring the Reviewer to enumerate every spec bullet and locate
the code path satisfying it before scoring. Measurement: re-run
`evals/fixtures/08-subtle-input-validation.yaml` 3-4 reps and compare
`30m20m` rejection rate against v2.7 F002 baseline (~25% → target ≥75%).

No SKILL.md changes. No helper changes. No new event types. No new evals.

## Hard prerequisite (block on this)

**v2.8 F001 full-fixture smoke must close PASS** before T4 starts.

Concretely: `package/.../docs/experiments/v2.8-learning-log/findings/F001-smoke.md`
must show:
- Smoke A (`01-trivial-typo.yaml`) → `meta.outcome=success`, `event_count=0`.
- Smoke B (`08-subtle-input-validation.yaml`) → at least one event with
  `event_type=reviewer_warn_or_fail`.

If Smoke B does not produce the event, v2.9 proceeds with rubric-only
fallback measurement and the T5 finding documents the degraded signal.

## Tasks

### T0 — Experiment scaffold + D001 (done)

- Create `package/.../docs/experiments/v2.9-reviewer-spec-coverage/`
  with README, JOURNAL, decisions/, findings/.
- Write D001 capturing single-pass-vs-multi-perspective decision + evidence
  selection + v2.8 prerequisite rationale.

**Status**: complete.

### T1 — Spec doc (done)

- Write Archive-level spec at
  `docs/superpowers/specs/2026-05-13-kws-claude-multi-agent-executor-v2.9-reviewer-spec-coverage-design.md`.

**Status**: complete.

### T2 — Plan doc (this file)

- Write Archive-level plan with T0..T7 breakdown.

**Status**: in progress (current).

### T3 — Advisor review on design

- Call advisor with full conversation context including v2.7 F002 evidence,
  v2.8 F001 status, and the design + plan as drafted.
- Address any blocking gaps before T4.

**Gate**: advisor sign-off (no BLOCKING items remaining).

### GATE — v2.8 F001 full-fixture smoke PASS

User-controlled. Requires:
- $20-50 budget approval for two `claude -p` runs on fixtures 01 + 08.
- `evals/run.sh` invocation with v2.8 helper integration active.
- F001 finding updated from DEFERRED → PASS (or DEFERRED → PARTIAL with
  documented fallback to rubric-only signal for v2.9).

**Owner**: user. v2.9 implementation does not start until this gate clears.

### T4 — Edit `references/reviewer-prompt.md`

**Step 1**: Read current `references/reviewer-prompt.md`. Locate the boundary
between the "**Before reviewing:**" paragraph and "**Part 1 — Spec Compliance:**".

**Step 2**: Insert new section. Heading: **"Spec Coverage Walk (REQUIRED — output BEFORE scoring)"**.
Body specifies TWO ordered sub-steps producing rows in one flat list:

**Sub-step A — Enumerate stated bullets.** For each happy-path example,
explicit error-case bullet, and "Notes" constraint in the injected
`{exact spec requirement text}` block: emit one line.

**Sub-step B — Adversarial generation for meta-rules.** Identify each
meta-rule (sentences containing *"strict"*, *"reject"*, *"anything else"*,
*"must validate"*, *"rule is"*, *"beyond these examples"*). For each
meta-rule, generate ≥3 adversarial inputs not explicitly listed in the
spec — drawn from at least: (i) repeated-unit/segment variants;
(ii) ordering/casing edge cases (uppercase, internal whitespace, trailing
unit-less integer); (iii) format combinations the spec implicitly excludes.
Emit one line per generated input.

Both sub-steps use the same row template:
  - `"<spec text fragment OR adversarial input>" :: <file>:<line>` (satisfied)
  - `"<spec text fragment OR adversarial input>" :: NOT FOUND` (implementer_omitted)
  - `"<spec text fragment OR adversarial input>" :: PARTIAL @ <file>:<line> — <why>` (capped at 0.7 SPEC_SCORE)

If any NOT FOUND row exists → `SPEC_FAULT: implementer_omitted` and the row
drives the top SPEC_ISSUES entry. The walk output **precedes** all existing
output fields.

Critical: sub-step B is the mechanism that closes F002's measured miss.
Sub-step A alone would not produce a `30m20m` row on fixture 08 (the
spec lists 5 explicit ValueError examples that do not include repeated
units). See D001 §Question 3 for the rationale and the pre-write
counterexample analysis.

**Step 3**: Extend the "## Output Format" section to add `SPEC_COVERAGE_WALK:`
at the top of the output block, before `SPEC_SCORE:`.

**Step 4**: No other prompt changes. Do not touch sub-agent dispatch in SKILL.md.
Do not touch the learning-event payload section.

**Acceptance**: prompt edit applied; `evals/check_skill_contract.py` still
passes (the contract eval does not check walk content, only the existing
contract fields).

### T4.5 — Cheap dry-run pilot (single rep, ~$5-10)

Before committing to the full T5 budget, run **one** rep of fixture 08 with
the v2.9 prompt and inspect the raw Reviewer output for sub-step B
behavior. This is a plan-level guardrail, not a statistical measurement.

**Step 1**: Run `evals/run.sh evals/fixtures/08-subtle-input-validation.yaml`
once. Capture the Reviewer sub-agent's raw output.

**Step 2**: Inspect `SPEC_COVERAGE_WALK:` block for:
- Presence of stated-bullet rows (sub-step A working).
- **Presence of ≥3 adversarial rows** including at least one repeated-unit
  case (e.g., `30m20m`, `1h1h`, `m1m`).
- No structural collapse (rows don't degrade into prose paragraphs).

**Acceptance**:
- If ≥3 adversarial rows including one repeated-unit case appear → proceed
  to T5 with confidence.
- If adversarial rows are absent or weak (only easy cases like `1H` uppercase
  that the existing Reviewer already catches) → iterate the prompt language
  in T4 (sharpen the adversarial-class taxonomy) before spending T5 budget.
- Failure modes here are cheap to fix: prompt edits only, ~$5-10 per
  iteration.

This task may run 1-3 cycles before T5. Each cycle = 1 prompt iteration
+ 1 rep. Cap at 3 cycles; if sub-step B still doesn't fire reliably after
3 prompt iterations, revert v2.9 and pivot to v2.10 multi-perspective
dispatch.

### T5 — Re-run fixture 08 (3-4 reps)

**Step 1**: Confirm budget. Estimated cost: $5-10 × 3-4 reps = $20-40.

**Step 2**: Run `evals/run.sh evals/fixtures/08-subtle-input-validation.yaml`
3 times (n=3). If results are unanimous (all PASS or all FAIL on `30m20m`),
stop. If split, add a 4th rep to break the tie.

**Step 3**: For each rep, capture:
- `rubric.json` pass_rate.
- Specific result of the `30m20m` rejection check.
- Reviewer raw output (`SPEC_COVERAGE_WALK:` content if present).
- `events.jsonl` from the v2.8 learning log (if Smoke B passed).

**Step 4**: Compute primary metric: rejection rate for `30m20m` check across
reps. Compare against F002 baseline (~25%).

**Acceptance**:
- Primary: rejection rate ≥75% (vs ~25% baseline).
- Secondary: SPEC_SCORE mean within 0.05 of F002 baseline (no significant
  new false-positive `implementer_omitted` flags).

**Power note**: n=3-4 with a binary outcome cannot cleanly separate
"miss rate ≤25%" from "miss rate ≤50%". With n=4, 1 miss = 25% (boundary),
2 misses = 50% (clearly fail). T6's finding doc frames results as pilot-
strength evidence, not statistical proof — language like *"pilot suggests
intervention works; n=4 cannot bound effect tighter than ±25%"*. Don't
expand n to fix this; document the limit.

### T6 — Findings doc + recommendation

Create `package/.../docs/experiments/v2.9-reviewer-spec-coverage/findings/F001-fixture08-walk.md`
with:
- Per-rep table (rubric pass_rate, `30m20m` result, SPEC_SCORE, NOT FOUND count).
- Mean and variance computations.
- Walk output samples (one rep's full SPEC_COVERAGE_WALK block).
- Comparison vs F002 baseline.
- Residual risks (Reviewer behavior on shorter-spec tasks; fallback signal
  if Smoke B did not pass).
- Recommendation: SHIP / DON'T SHIP / NEEDS MORE DATA.

If recommendation = SHIP, proceed to T7. Otherwise revert the prompt edit and
record the negative result; recommend v2.10 multi-perspective dispatch.

### T7 — Release metadata (only if T6 = SHIP)

- `manifest.json`: skill version 2.8.0 → 2.9.0; package version bump.
- `README.md`: version table row + v2.9.0 entry.
- `CHANGELOG.md`: v2.9.0 entry referencing F001 evidence.
- `HISTORY.md`: v2.9.0 row under §1; experiment row under §3.
- `ARCHITECTURE.md`: no changes (no architectural surface affected).
- Final commit on the v2.9 branch.

### T8 — Final advisor done-check + merge prep

- Call advisor with the full v2.9 experiment record + T6 finding.
- Address any blocking items before merge.
- Merge readiness: v2.9 branch up to date with main, all preflight evals
  passing, finding doc closed.

## Plan self-review

- **T0-T3 cost**: zero API spend (local writing + one advisor call).
- **GATE cost**: $20-50 (v2.8 F001 smoke; budget approval required).
- **T4 cost**: zero (prompt edit only).
- **T4.5 cost**: $5-10 per cycle × up to 3 cycles = $5-30 (cheap iteration on
  prompt language before committing T5 budget).
- **T5-T6 cost**: $20-40 (3-4 fixture 08 reps).
- **Total v2.9 spend**: $45-120 worst case, contingent on Path A discipline.
- **Surface area**: 1 prompt file modified, 0 helper changes, 0 SKILL.md
  changes, 0 new evals. Smallest possible v2.x increment.
- **Reversibility**: T4 is a single-file change. If T5 returns negative,
  T4 reverts cleanly with one Edit.
- **Evidence-traceability**: every step references F002 evidence; nothing
  is speculative beyond the prompt-mechanism hypothesis.

## Links

- Spec: `docs/superpowers/specs/2026-05-13-kws-claude-multi-agent-executor-v2.9-reviewer-spec-coverage-design.md`
- Experiment record: `package/.../docs/experiments/v2.9-reviewer-spec-coverage/`
- D001: `package/.../docs/experiments/v2.9-reviewer-spec-coverage/decisions/D001-initial-design.md`
- v2.7 F002 (evidence): `package/.../docs/experiments/v2.7-quality-mode/findings/F002-close-out.md`
- v2.8 F001 (hard prerequisite): `package/.../docs/experiments/v2.8-learning-log/findings/F001-smoke.md`
- Current Reviewer prompt: `package/.../references/reviewer-prompt.md`
- Fixture 08: `package/.../evals/fixtures/08-subtle-input-validation.yaml`
