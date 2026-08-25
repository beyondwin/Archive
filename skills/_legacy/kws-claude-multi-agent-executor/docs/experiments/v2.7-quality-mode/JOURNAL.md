# JOURNAL — v2.7 Quality Mode Experiment

Chronological log of design decisions, problems encountered, reviews received,
and direction changes. Each entry is dated; commit SHAs are referenced where
applicable.

---

## 2026-05-13

### 13:00 — Orchestration pattern discussion (session genesis)

User asked to discuss orchestration patterns: Opus orchestrator + Sonnet workers
structure, single-session vs multi-session trade-offs, new topologies. The
conversation surveyed:

- Current v2.6.0 topology: central Orchestrator (Opus) + isolated Sonnet
  sub-agents (Implementer / Reviewer / Verifier / Documenter / Plan Reviewer),
  P2 wave-parallel sub-worktrees, P4 0.0–1.0 scoring.
- Trade-off axes: fixed cost per sub-agent, context window pressure, parallelism,
  cross-cutting quality, resumption.
- Topology candidates: orchestrator-worker (current), adversarial critic,
  best-of-N branching, inverted heaviness (Sonnet orchestrator), blackboard,
  hierarchical 2-tier.

### 13:30 — Pivot to "quality over speed"

User asked: if quality is the priority (not speed), what should we invest in?

Recommended bundle ("v2.7 Quality Mode"):
1. Best-of-N + Opus judge on HIGH-risk tasks
2. Reviewer split (spec / code-quality / security) with unanimous PASS required
3. Implementer self-critic loop
4. P4 score thresholds raised (0.92 / 0.85)
5. P5 SMALL-bucket TDD skip removed
6. P2 parallel dispatch disabled (or capped)
7. Verifier always runs
8. Implementer/Reviewer escalated to Opus

### 14:00 — Model-routing question

User asked: does the orchestrator auto-decide Opus vs Sonnet per task?

Finding: **No, currently hardcoded.** SKILL.md line 1015 says
"Models: Orchestrator=Opus, Sub-agents=Sonnet". `Agent` tool accepts a `model`
param but the skill never passes one. Auto-routing is a new feature.

Discussed: Static (risk-tiered), Dynamic (per-task), Mode flag, Hybrid.
**Decision**: Hybrid (D-future) — `mode` flag with per-risk overrides.

### 14:30 — Floor-level debate

User instinct: in quality mode shouldn't ALL tasks be HIGH?

Reframed: risk tier = **blast radius**, not **quality bar**. Three options:
- α (MID floor) — LOW → MID, MID stays MID, HIGH gets best-of-N + Opus
- β (HIGH floor) — everything HIGH, best-of-N everywhere
- quality_plus — α + MID also gets best-of-N

User questioned whether MID's "few reasonable implementations" assumption
holds. Decision: **test empirically** rather than assume.

→ [D001](./decisions/D001-floor-level.md): floor at MID, with quality_plus
as test variant for MID.

### 15:00 — User said: full experiment, not variance probe

Proposed two paths:
- **Variance probe** (cheap, ~$30): same MID task × 3 dispatches, see if
  outputs differ enough for best-of-N to add signal
- **Full experiment** (~$300–900): implement modes, 5 fixtures × 3 modes × n
  reps

User chose: full experiment.

### 15:30 — ADVISOR REVIEW (first)

Before substantive work, called advisor. Advisor flagged 7 issues:

1. **Statistical power broken** — n=1 per cell can't detect <huge effects
2. **No pilot before scaling** — 4 fixtures + rubrics designed without trying one
3. **Judge calibration is prerequisite** — must verify judge can discriminate ≥0.2
4. **Cost estimate light** — Opus implementer + Opus judge + best-of-3 → $30–50/run, not $5–10
5. **Confirmation bias** — α framing tilts toward "α wins"; experiment must be
   able to cleanly return "user was right, plus wins"
6. **Don't modify production SKILL.md** — v2.6.0 baseline just stabilized
7. **Unasked question** — is there a real plan failing on v2.6.0, or preemptive?

→ [D005](./decisions/D005-experimental-branch.md): branch-based
→ [D006](./decisions/D006-pilot-first.md): pilot first

### 16:00 — User confirmed: preemptive, proceed anyway

Q1: Real failure case? → No, gut-based hypothesis.
Q2: $300–900 budget OK? → Yes, proceed.

Reaffirmed pilot-first approach. Created tasks #1-#7.

### 16:15 — Branch created

`feature/v2.7-quality-mode-experiment` from main. Production SKILL.md untouched.

### 16:30 — Fixture 08 design

Designed `parse_duration()` MID-risk fixture. 15 edge cases in spec → 20
deterministic rubric checks (10 valid + 10 error). Bugs naive Sonnet tends
to miss: internal whitespace, uppercase units, repeated unit, decimal,
bare unit.

### 17:00 — Judge calibration round 1 (Sonnet)

Built `evals/calibration/` with good_impl + broken_impl. Both pass
limited test suite (test coverage doesn't catch the 4 silent-accept bugs).

Sonnet judge × 3 reps each:

| Axis | good | broken | Δ |
|------|------|--------|---|
| correctness | 0.7 | 0.4 | +0.30 ✓ |
| spec_compliance | 0.4 | 0.4 | 0.00 ✗ |
| code_quality | 0.50 | 0.27 | +0.23 ✓ |
| cost_efficiency | 1.0 | 1.0 | 0.0 (artifact) |
| **mean** | **0.64** | **0.52** | **+0.13 ❌** |

Problem: cost_efficiency stuck at 1.0=1.0 (same fake numbers diluted mean);
spec_compliance not using diff to discriminate. Sonnet directionally
correct but mean-delta < 0.2 threshold.

### 17:30 — Judge calibration round 2 (Opus, with docstring cue)

Opus judge × 3 reps each: **Δ = 0.32 ✓**.

But notes revealed Opus used the docstring marker
"INTENTIONALLY BUGGY for judge calibration" as evidence. Contaminated.

### 18:00 — Judge calibration round 3 (Opus, cue removed)

Cleaned `broken_impl.py` to have a neutral docstring and no `# BUG:` comments.

Re-ran Opus × 3 reps: **Δ = 0.10 ❌**

Opus still correctly identified the bugs in `notes` ("misses repeated-unit,
internal-whitespace..."), but assigned proportional partial credit (16/20 →
0.7 correctness, 20/20 → 0.9). Plus high per-rep variance on code_quality
(±0.16 std on good).

Conclusion: **LLM judge alone cannot reliably hit 0.2 mean threshold on small
behavioral deltas**. The variance + partial-credit fairness mean we need a
different measurement approach.

### 18:30 — Pivot: deterministic rubric runner

Insight: the rubric in fixture 08 is **mechanical** — 20 shell commands that
either pass or fail. There's no reason to ask an LLM to estimate something a
shell script can verify exactly.

Wrote `evals/rubric.py` that runs each `check:` against a workdir. Result:

- good_impl: 20/20 = 1.00 pass_rate
- broken_impl: 16/20 = 0.80 pass_rate
- **Deterministic Δ = 0.20** ✓

Calibration PASSES via the deterministic measurement. LLM judge will
supplement with subjective code_quality only.

→ [D003](./decisions/D003-rubric-runner.md): rubric.py as primary
correctness signal.

### 19:00 — Fixture 08 scope refinement

Realized: both fixture 08 tasks are MID risk. With quality modes:
- `balanced`: standard Sonnet × 2 tasks
- `quality_alpha`: identical to balanced (no HIGH tasks to trigger best-of-N)
- `quality_plus`: only mode that differs (MID gets best-of-N)

→ [D004](./decisions/D004-pilot-scope.md): pilot = balanced vs quality_plus
only (6 runs). Quality_alpha needs HIGH-fixture validation later.

### 19:30 — Commit d5aa5eb

Calibration work + fixture 08 + rubric.py committed to experiment branch.

### 20:00 — Documentation establishment (this entry)

User instructed: "stop asking, finish it, and version-document every decision
and review along the way." Wrote `docs/experiments/v2.7-quality-mode/` with
README + JOURNAL + ADR files. Continuing autonomously per user direction.

### 20:30 — Harness integration (commit cc2cf6e)

Modified `evals/run.sh`:
- After `test_after` runs, invoke `rubric.py` if fixture has `expected.rubric`
- Result saved to `.harness/rubric.json`, appended to judge input as
  `#### rubric_results` section
- Print `rubric pass_rate` to harness stdout

Modified `evals/judge.md`:
- Added section instructing judge to derive `correctness` from
  `rubric_results.summary.pass_rate` mechanically
- Added section for `spec_compliance` from `rubric_results.error_cases.passed/total`
- LLM judge falls back to diff/test estimation only when rubric absent

### 21:00 — Drafted best-of-N judge prompt (in references/)

`references/best-of-n-judge-prompt.md` — Opus judge template for quality_plus
mode's parallel-candidate selection. Weighted composite scoring
(0.5 rubric + 0.3 code_quality + 0.2 risk). Includes escalation path when
all candidates are weak.

### 21:15 — Ceiling check run on fixture 08 → **CEILING HIT**

Ran `bash evals/run.sh fixtures/08-*.yaml` against unmodified v2.6.0 (balanced).

Result: **rubric pass_rate = 1.0** (20/20 checks pass). Judge mean: 1.0.

Sonnet aces the fixture. Cause: original spec enumerated all 15 edge cases
explicitly, making the fixture a reading-comprehension test rather than a
judgment test.

→ [D007](./decisions/D007-fixture-realistic-spec.md): rewrite spec to a
realistic underspec while keeping the rubric. The 4 "naive miss" categories
(internal whitespace, uppercase, repeated unit, bare unit) removed from
spec text. Spec now lists happy-path + obvious errors, then says "strictly
validate the grammar — these examples are not exhaustive."

### 21:30 — Re-run ceiling check on rewritten fixture 08 (commit d0cbd9a)

Result: **rubric pass_rate = 0.95** (19/20 checks).

The one missed check: `"repeated unit raises ValueError"` —
`parse_duration("30m20m")` silently accepted instead of raising.

The other 3 "naive miss" categories I removed from spec
(internal whitespace, uppercase units, bare unit) were caught anyway.
Reason: a regex-based or grammar-based parser naturally rejects them as
"input doesn't match `<integer><unit>` pattern." Only "repeated unit" is
a higher-order semantic judgment call ("did I already see this unit?")
that requires explicit memory.

### 21:40 — ADVISOR REVIEW (second)

Surfaced the 0.95 result + plan to implement D008 (~150-line SKILL.md
change). Advisor pushed back hard:

1. **0.95 is the experiment's answer, not a problem to design around.**
   3 of 4 naive-miss predictions were wrong — Sonnet handles them natively.
   Only 1 edge case (repeated unit) is actually missing from balanced.
2. **Need n=3 baseline variance before any SKILL.md surgery.** Could be
   reliably 0.95 (small detectable ceiling), wildly variable (noise floor
   too high), or 1.0 sometimes (single-shot lucky). Spend $20 to learn
   which.
3. **Don't iterate fixture again.** That's the confirmation-bias trap
   (advisor #5). Either accept the data or pivot domain.
4. **Calibration infrastructure (rubric.py, judge integration) is worth
   shipping regardless.** quality_plus hypothesis specifically is weak.
5. **"Honest framing"**: data says v2.6.0 is closer to a solved problem
   on realistic MID tasks than expected. That's a *finding*, not a failure.

### 22:00 — Decision: baseline variance probe first

Running balanced × 2 more reps on fixture 08. Then:

- If all 3 reps land at 0.95 with the same single miss → write findings
  document, ship rubric.py + judge update, close v2.7-quality-mode
  experiment with negative result on quality_plus
- If variance is high (e.g., reps land at 0.85, 0.95, 1.00) → quality_plus
  cannot be measured with n=3 on this fixture; revisit
- If some reps land at 1.0 → balanced is already at ceiling reliably;
  experiment closed

The advisor's reframe: **finish the experiment by following the data,
not by patching the fixture until quality_plus has room to win**.

### Next steps (autonomous, current position)

1. Run balanced × 2 more on fixture 08 (in series — harness baseline file
   would race on parallel)
2. Analyze 3-rep variance
3. Write `findings/F001-fixture08-baseline.md` with the result
4. Decide implementation: implement quality_plus + pilot, OR skip
   implementation and ship calibration infrastructure only
5. Final commit + close-out summary

### 22:30–23:00 — 3-rep ceiling check complete

Reps 1, 2, 3 all returned identical 0.95 pass_rate with same single miss.
Wrote F001 + F002, marked experiment CLOSED, merged infrastructure to main
(commit 0a9c2ef).

### 23:30 — Guide documentation + auto-update system

Added ARCHITECTURE.md (13-section overview), updated AGENTS.md with
ARCHITECTURE.md sync protocol, cross-referenced in HISTORY.md. Committed
to main (commit d5c4d01).

### 23:45 — ADVISOR REVIEW (third)

After "experiment archived" claim, advisor noted: the post-merge
infrastructure was never smoke-tested on main. The 3 ceiling reps were
on the experiment branch. Need one fixture-08 run from main to confirm
the merged infrastructure produces the expected rubric pipeline output.

### 23:50 — Smoke test on main — UNEXPECTED FINDING

Ran fixture 08 on main. Expected: 0.95, "repeated unit" miss.
**Actually got: 1.00, zero misses.**

This contradicts the "zero variance" conclusion from n=3. The 4th rep
catches the edge case that the previous 3 missed. Updated reading:
balanced misses "repeated unit" ~75% of the time, not 100%.

Updated F001 + F002 with n=4 data and revised math. quality_plus
expected gain revised from ~+0.05 to ~+0.017. Recommendation to NOT
implement still holds — even smaller expected effect.

Noted in F002: cheaper alternative not pursued — just escalate
Implementer to Opus on HIGH-risk tasks. ~10-line SKILL.md change, no
best-of-N machinery. Worth considering if a real failure case ever
justifies investigation.

### Final state

- Experiment archived with n=4 data and revised recommendation
- Infrastructure on main (smoke-verified)
- Documentation system in place (ARCHITECTURE + AGENTS protocol)
- Branch preserved for D008 reference if revived
