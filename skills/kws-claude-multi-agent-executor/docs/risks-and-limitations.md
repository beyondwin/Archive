# Risks and limitations

A consolidated, honest register of known fragilities, partial validations,
and open issues in this skill. Each entry has a current status, a concrete
manifestation, and a pointer to where it's tracked or being addressed.

This file is the answer to "what could break?" — read it before making
non-trivial changes, and update it when shipping anything that changes the
risk profile.

---

## Status legend

- **★★★ Active risk** — production-relevant; could break for users right now.
- **★★ Tracked risk** — known but bounded; specific mitigation in place.
- **★ Acknowledged limitation** — recognized constraint, not actively bad.
- **CLOSED** — was a risk; now resolved by a specific change.

---

## Skill-execution risks

### ★★ Orchestrator adherence to SKILL.md instructions

**Manifestation**: Under headless `claude -p --dangerously-skip-permissions`,
the orchestrator can skip prose-only instructions when contextual load is
high (multi-task plans, longer specs). v2.8 F001 Smoke B documented this
empirically: 0 of 47 Bash invocations executed Step 7.5 init-run despite the
instruction.

**Mitigation in place** (v2.8.1):
- Step 7.5 heading promoted to MANDATORY.
- `LEARNING_LOG_INIT:` marker printed and detected post-run.
- `evals/run.sh` reports `learning_log_adherence: yes|no (markers=N)` per fixture.
- 18th contract check locks the MANDATORY framing in SKILL.md.

**Remaining concern**: All mitigations are prose + observability. A
determined skip is still possible. Hook-based enforcement (PreToolUse hook
that auto-runs init-run before the first Bash call) would be the structural
fix but adds scope.

**Tracked in**: [`deferred-candidates.md`](./deferred-candidates.md) §Hook-based enforcement.
**Reference**: HISTORY.md v2.8.1 entry; `docs/experiments/v2.8-learning-log/findings/F001-smoke.md`.

### ★★ Headless model gap

**Manifestation**: SKILL.md documents "Orchestrator=Opus, Sub-agents=Sonnet"
but none of the 6 `claude -p` dispatch sites pass `--model`. The actual model
inherited is whatever the user's Claude Code CLI default is at invocation.

**Why this matters**: If a user has set their default to Sonnet for cost
reasons, the orchestrator is silently running on Sonnet despite the
documented contract. Risk-tier-driven TDD strictness is unaffected (it's
prompt-level), but reasoning depth on hard tasks may be lower than expected.

**Mitigation**: None yet. Documented in v2.8 D001 (out-of-scope decision).
Candidate: pass `--model claude-opus-4-7` explicitly on each `claude -p`
invocation in Resume Chain + sub-agent dispatch sites.

**Tracked in**: [`deferred-candidates.md`](./deferred-candidates.md) §Headless model flag.
**Reference**: `docs/experiments/v2.8-learning-log/decisions/D001-initial-design.md` §Out-of-scope.

### ★ `CLAUDE_SESSION_ID` env propagation under various dispatch modes

**Manifestation**: The learning-log helper uses `$CLAUDE_SESSION_ID` for
`session_short` in run_id. If unset, falls back to `nosession`. v2.8 F001
Smoke A showed `session_id="eval"` (not nosession), meaning the env var IS
sometimes propagated but the value format varies.

**Impact**: Cosmetic for now. Worst case: less-unique run_ids when multiple
runs start in the same second (mitigated by pid in run_id).

**Mitigation**: None needed; run_id uniqueness is preserved by pid.

**Reference**: F001-smoke.md §Residual risks §4.

---

## Measurement / validation risks

### ★★★ Pilot-strength evidence, not statistical proof

**Manifestation**: v2.9.0 ship decision is based on n=4 reps on fixture 08.
With binary outcome, 95% Clopper-Pearson lower bound is ~40% (cannot bound
the true rejection rate tighter than ±60%).

**What's defensible**: 4/4 PASS under F002's 25%-catch null has probability
~0.4%. Strong rejection of "intervention does nothing".

**What's NOT defensible**: Claiming "Reviewer never misses `30m20m` again"
or extrapolating the +75pp effect to other fixtures. Pilot-strength = "the
intervention is correctly aimed and probably works; full confidence requires
longer-term observation under real usage."

**Mitigation**: Documented in F002-T5-n4-results.md §Power note. Future
ship decisions should record similar power notes whenever n is below ~20.

**Reference**: `docs/experiments/v2.9-reviewer-spec-coverage/findings/F002-T5-n4-results.md` §Power note.

### ★★ Single-fixture optimization risk

**Manifestation**: v2.9's Spec Coverage Walk was designed against fixture 08
exclusively (the only measured-failure fixture in the corpus). Whether the
walk's adversarial-class taxonomy (repeated-segment / ordering-casing /
format-excluded) generalizes to other domains (concurrency, security,
API design) is empirically untested.

**Mitigation**: None in current scope. Two acceptable paths forward:
1. During the next routine baseline capture (any fixtures 01-07), inspect
   `SPEC_COVERAGE_WALK:` output for quality.
2. When a *new* failure surfaces in production usage (via the learning
   log), re-evaluate whether the walk handles the new domain.

### ★★ Combined-intervention attribution (v2.9 + v2.8.1 + spec clarify)

**Manifestation**: T5 stacked three changes simultaneously: v2.9 prompt
(Spec Coverage Walk), v2.8.1 enforcement, and fixture 08 spec clarification.
The 100% rejection rate is the joint effect; individual contributions are
not measured.

**What we know from F002-T5 §Attribution**:
- Spec clarification (Phase 2) is likely the biggest single contributor —
  removes the defensible "spec permits repeated units" reading.
- v2.9 walk makes the consideration deterministic across reps.
- v2.8.1 enforcement is the observability prerequisite (no learning log =
  no future evidence).

**Mitigation**: Documented but not measured. Ablation experiments (spec-only,
walk-only, enforcement-only) would clean this up but were not run because
T5 met the ship criteria. Future post-hoc analysis with more runtime data
can isolate contributions.

### ★ Sub-step B output drift on shorter / test-side specs

**Manifestation**: T4.5 dry-run observed Task 1 Reviewer (reviewing the
tests file rather than implementation) used sub-step B as *enumeration of
cases the test parametrize covers* rather than *generation of independent
adversarial cases*. On fixture 08 this didn't matter (the test parametrize
was comprehensive); could matter on partial test suites.

**Mitigation**: Not blocking; flagged for monitoring. If a future fixture
has a sparse test parametrize, sub-step B may give a false-pass result.

**Reference**: F001-T4.5-dry-run.md §Residual risks.

---

## Branch / repository hygiene risks

### ★ Long-lived shared branch `codex/executor-learning-log`

**Manifestation**: v2.8, v2.8.1, v2.9 design + ship commits all live on
this branch (shared with the user's parallel Codex executor work). Main
has not received these yet. Cross-references to v2.8 paths in v2.9 docs
only resolve on this branch.

**Mitigation**: When ready to merge, the Claude executor commits are
path-isolated; the user's Codex commits should land separately. Merging
both together requires care.

**Recommended sequence**:
1. v2.9 + v2.8.1 + v2.8 → main as one merge (Claude executor only).
2. Codex executor work → main as a separate merge.
3. v2.10 (when started) cuts from updated main.

### ★ Sub-experiment work happens on shared branches

**Manifestation**: v2.8 + v2.9 share `codex/executor-learning-log`. Future
experiments may collide more aggressively if the user is also working on
the same branch.

**Recommendation**: For v2.10+, cut a Claude-only feature branch from main
if the user is concurrently working on a different topic on shared branches.

---

## Eval-system risks

### ★★ Eval cost concentration

**Manifestation**: Each fixture run = $5-15 + 15-30 min wall. Full 8-fixture
sweep = $40-120 + 2-3 hours. This caps eval frequency — no "run on every
commit" is feasible.

**Mitigation**: Preflight checks (33 deterministic) run for free and catch
contract regressions before any `claude -p` invocation. The expensive eval
runs only at major-version ship time.

**Recommendation**: Treat baseline capture as a deliberate event, not a
CI step. Document the run in the relevant experiment finding.

### ★ Single-rep baseline overrides

**Manifestation**: `evals/baselines/v<X>.json` is overwritten by the most
recent `bash evals/run.sh` invocation. n=4 reps in a chain leave only the
last as the persisted baseline.

**Mitigation**: Per-rep run dirs in `~/.claude/learning/...` carry the full
chain. Cross-rep data lives in the experiment's `findings/F00N-*.md` file,
not in `baselines/`.

**Recommendation**: Baselines are version snapshots, not rep aggregates.
Acceptable as-is.

### ★ Spec ambiguity vs rubric strictness in fixtures

**Manifestation**: v2.9 T4.5 found fixture 08's spec excerpt was ambiguous
on `30m20m` (the rubric required ValueError; the spec didn't explicitly
forbid repeated units). Resolved in Phase 2 by clarifying the spec.

**Open question**: Other fixtures (01-07) have not been audited for similar
spec-vs-rubric mismatches. Possible source of confusing T5-style results
if encountered.

**Mitigation**: Manual audit of fixtures 01-07 is candidate work. Track in
[`deferred-candidates.md`](./deferred-candidates.md) §Fixture spec audit.

---

## Observability risks

### ★★ Adherence marker is spoofable

**Manifestation**: `LEARNING_LOG_INIT:` marker is detected via regex on
run.jsonl. A determined skip could *print* the string without actually
calling `init-run`.

**Mitigation in place**: Cross-check filesystem state — was a new run dir
actually created in `~/.claude/learning/...`? Already done in T5 audit
(4/4 reps had new run dirs).

**Hardening candidate**: Hook-based enforcement (PreToolUse). Tracked in
deferred-candidates.

### ★ Learning log doesn't fire on Resume Chain unless `MAE_LEARNING_RUN_ID`
   env is propagated

**Manifestation**: Resume Chain's `nohup claude -p ...` must be prepended
with `env MAE_LEARNING_RUN_ID="$..." nohup ...` for the chained orchestrator
to continue writing to the same run.

**Mitigation in place**: SKILL.md Phase 0 Resume Chain step 4 explicitly
documents this. Tested at shell level in F001 Smoke A (but not in a real
Resume Chain — the smoke didn't trigger compaction).

**Reference**: F001-smoke.md §Residual risks §2.

---

## Closed / resolved (kept for reference)

### CLOSED — Init-run silent failure under multi-task plans (was ★★★)

**Was**: v2.8 F001 Smoke B showed 0 of 47 Bash calls executed Step 7.5.
**Closed by**: v2.8.1 enforcement (MANDATORY framing + marker + eval check).
**Verified by**: T5 n=4 reps, all 4 emitted ≥7 markers + created new run dirs.

### CLOSED — `30m20m` Reviewer silent miss (was ★★★)

**Was**: v2.7 F002 measured ~75% Reviewer miss rate. T4.5 single rep showed
walk surfaced the case but Reviewer reasoned the spec allowed it.
**Closed by**: v2.9.0 walk + Phase 2 spec clarification.
**Verified by**: T5 n=4 reps, 100% rejection rate (8/8 Reviewer invocations
explicitly handled `30m20m`).

### CLOSED — Sub-agent env propagation ambiguity (was ★★)

**Was**: Original v2.8 design assumed all sub-agents could call the helper
via inherited `MAE_LEARNING_RUN_ID`. Advisor caught that Agent-tool dispatch
doesn't guarantee env propagation.
**Closed by**: v2.8 D001 §Q4 single-writer contract — sub-agents write
candidate JSON files; orchestrator is sole caller.

---

## How to update this file

When you ship a change that affects the risk profile:

1. If you **close** a risk → move it to "Closed / resolved" with `verified by` link.
2. If you **introduce** a risk → add a new entry with status ★ to ★★★, manifestation,
   mitigation, and tracking pointer.
3. If you **mitigate** an existing risk but don't fully close it → update its
   mitigation section + downgrade ★★★ → ★★ or ★★ → ★ as appropriate.

This file's accuracy decays without maintenance. Prefer truth-with-staleness
over abandonment.
