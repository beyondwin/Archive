# Skill History — kws-claude-multi-agent-executor

A two-axis summary of where this skill came from and what changed:

- **§1 Version timeline** — chronological version notes
- **§2 Improvement areas** — grouped by topic, with which versions touched each

Source of truth for skill behavior: `SKILL.md` (current version in frontmatter).
This file is for *humans navigating the history*.

Update protocol: see `AGENTS.md` ("Experiment & history record-keeping").

---

## §1 Version timeline

### v2.9.0 — Reviewer Spec Coverage Walk (2026-05-14)

Inserts a deterministic "Spec Coverage Walk" pass into
`references/reviewer-prompt.md`, requiring the Combined Reviewer to
emit a `SPEC_COVERAGE_WALK:` block before scoring. The walk has two
ordered sub-steps:

- **Sub-step A** — Enumerate stated spec bullets (happy-path examples,
  explicit error-case bullets, Notes constraints) with a strict row
  template `"<frag>" :: <file>:<line> | NOT FOUND | PARTIAL`.
- **Sub-step B** — Adversarial generation for spec meta-rules. For each
  meta-rule (sentences containing "strict", "reject", "anything else",
  etc.), generate ≥3 adversarial inputs not explicitly listed in the
  spec, drawn from at least these classes: repeated-segment variants,
  ordering/casing/whitespace edges, format combinations the spec
  implicitly excludes.

Why this exists:
- v2.7 F002 documented a Reviewer miss rate ~75% on `parse_duration("30m20m")`
  ValueError. Root cause: Sonnet's regex/grammar instinct read the spec
  as "natural language about non-repeated units" and never explicitly
  tested whether `30m20m` was rejected anywhere in the implementation.
- The pre-write analysis (v2.9 D001 §Question 3) showed enumeration of
  stated bullets alone would not surface `30m20m` — the case is covered
  only by the spec's meta-rule "strict validation of the grammar."
  Adversarial generation from meta-rules is the critical mechanism.

Empirical validation (T5, n=4 reps on fixture 08):
- `30m20m` rejection rate: F002 baseline ~25% → v2.9.0 **100% (4/4 reps)**.
- 8 of 8 Reviewer invocations across the 4 reps emitted `SPEC_COVERAGE_WALK`
  and explicitly included a `30m20m` row.
- SPEC_SCORE mean 0.997 (no false-positive `implementer_omitted` flags).
- v2.8.1 adherence verified: 4/4 reps with markers + run dirs created.

Combined intervention attribution: spec-clarification (fixture 08 yaml
patch — explicit "unit may appear at most once" note) is the biggest
single contributor; the walk makes the consideration deterministic and
reproducible. Without the walk, the spec-clarification result would
still depend on whether the Reviewer happens to scan for the case.

Out of scope (deferred candidates):
- Multi-perspective Reviewer dispatch (omc Team pattern). Single-pass
  enumeration solved the F002 case; multi-perspective is candidate work
  for v2.10+ only if a non-fixture-08 failure surfaces that requires it.
- Walk pattern extension to Verifier (acceptance-criteria coverage walk).
  Deferred — Verifier failure rate not measured at this granularity.

See `docs/experiments/v2.9-reviewer-spec-coverage/findings/F002-T5-n4-results.md`
for the full ship analysis.

### v2.8.1 — Step 7.5 enforcement (MANDATORY framing + adherence marker) (2026-05-13)

Empirical fix for the adherence gap found in v2.8 F001 Smoke B: 47 of 47
Bash invocations in a fixture-08 run skipped the learning-log helper
despite SKILL.md instructing it. Root cause: Step 7.5 under heavier
contextual load (multi-task plans) was read as advisory rather than
mandatory.

Changes:
- SKILL.md Step 7.5 heading promoted to MANDATORY; "DO NOT SKIP" framing
  added. Stronger imperative language reused from worktree-creation
  Phase 0 checkpoints.
- Helper invocation block now emits `LEARNING_LOG_INIT: RUN_ID=<id>` on
  success and `LEARNING_LOG_INIT: SKIPPED (...)` on shell-level failure.
  These markers surface in run.jsonl and enable post-run adherence audit.
- `2>/dev/null` removed from the init-run call — helper stderr now visible
  if the script breaks.
- `evals/run.sh` now greps run.jsonl for the `LEARNING_LOG_INIT:` marker
  after each fixture and reports `learning_log_adherence: yes|no` plus
  marker count. Non-blocking; observability-only.
- `evals/check_skill_contract.py` gains an 18th check (`skill_md_v281_mandatory_framing`)
  asserting the MANDATORY / DO NOT SKIP / LEARNING_LOG_INIT tokens are
  present in SKILL.md.

What this does NOT fix:
- Adherence is still prose-based (no PreToolUse hook). A determined
  skipping is still possible. The marker + eval check make it visible
  rather than silent. Hook-based enforcement is candidate work for v2.10+.
- v2.9 (Reviewer Spec Coverage Walk) is unaffected by this change. The
  walk's measurement infrastructure can now rely on the learning log
  firing for multi-task plans.

### v2.8 — Learning log + review-side superpowers Skill calls (2026-05-13)

Adds a user-local per-run sharded learning log so notable boundaries
(reviewer WARN/FAIL, verifier FAIL, sub-agent ESCALATE, recurring issues,
parallel dispatch failures, successful workarounds, actionable completion
learnings) can drive future skill improvements. Sibling pattern to
`kws-codex-plan-executor`'s learning log, adapted for the Claude Code
runtime.

Key changes:
- New `scripts/append_learning_event.py` with 4 idempotent subcommands
  (`init-run`, `append`, `close-run`, `append-session-id`).
- New `references/learning-log.md` reference doc.
- New `evals/check_learning_log.py` (16 deterministic checks) and
  `evals/check_skill_contract.py` wired into `evals/run.sh` as preflight.
- SKILL.md Phase 0 Step 7.5 / Phase 1 Step 3.5 / Phase 2 Step 2 / Escalation
  Protocol / Resume Chain instrumented for lifecycle calls.
- Single-writer contract: orchestrator only — sub-agents write candidate
  JSON files under `<worktree>/.orchestrator/learning_events/`.
- Resume Chain handoff preserves `MAE_LEARNING_RUN_ID` via env propagation
  and calls `append-session-id` (NOT `init-run`).
- Review-side superpowers Skill invocations added:
  - Plan Reviewer → `Skill("superpowers:writing-plans")`
  - Reviewer → `Skill("superpowers:requesting-code-review")`
  - Verifier → `Skill("superpowers:verification-before-completion")`
- ARCHITECTURE.md §14 Learning Log Contract added.
- All helper calls wrapped to fail silently — observability never blocks
  plan execution.

Records: `docs/experiments/v2.8-learning-log/`
Branch: `codex/executor-learning-log`

### v2.7 — Quality-mode experiment (2026-05-13)
**Branch only** — not merged to `main`. **Negative result** on quality_plus mode.

Hypothesis: best-of-3 Opus implementers + Opus judge would improve MID-task
output quality. Outcome: balanced v2.6.0 on a realistic-spec MID fixture
hits 0.95 rubric pass_rate with zero variance across 3 reps. Ceiling for
quality_plus is +0.05 max and 3/3 reproducible misses mean best-of-N
wouldn't discriminate.

Infrastructure built during the experiment is worth merging independently
(see §2 Evaluation harness).

Records: `docs/experiments/v2.7-quality-mode/`
Branch: `feature/v2.7-quality-mode-experiment`

### v2.6.0 — Eval-harness stabilization (2026-05-12)
- Eval harness fixes (Fix A, Fix B, isolation)
- Worktree path coverage
- v2.6.0 baseline JSON captured
- P6 eval suite infrastructure
- Commits: `80c0c39`, `c9ab406`, `ffe45fd`, `31308f9`, `b16e7ab`

### v2.5.x — Hooks / preflight / scoring (estimated)
Per `DESIGN-v2.5.md`:
- P1: Native Claude Code hooks for gate enforcement
- P3: Plan Reviewer preflight sub-agent
- P4: Generator-Verifier 0.0–1.0 scoring (replaces binary PASS/FAIL)
- P5: Effort-scaling rules in Implementer prompts (SMALL/MEDIUM/LARGE buckets)

### v2.4.0 — Canonical orchestrator-worker (2026-05-08)
- Anthropic-canonical Opus orchestrator + Sonnet workers
- git worktree isolation
- `state.json` external memory
- Risk-tiered verification (LOW batch, MID/HIGH per-task)
- P2: Wave-parallel sub-worktree dispatch for independent tasks
- Skill added to the executor skill inventory

---

## §2 Improvement areas

### Orchestration topology
Opus Orchestrator + Sonnet workers (Implementer / Reviewer / Verifier / Documenter / Plan Reviewer).

| Version | Change |
|---------|--------|
| v2.4.0 | Established canonical orchestrator-worker pattern |
| v2.5.x | Added Plan Reviewer preflight (P3) |
| v2.7 (proposed, deferred) | Best-of-N + Opus judge for MID/HIGH tasks (D008 design preserved, not implemented — see v2.7 findings) |

### Risk tiering & effort scaling
LOW/MID/HIGH risk tiers control verifier dispatch, effort bucket, and (proposed) model selection.

| Version | Change |
|---------|--------|
| v2.4.0 | LOW = batch verifier; MID/HIGH = per-task verifier |
| v2.5.x | P5: SMALL/MEDIUM/LARGE effort buckets per task complexity |
| v2.7 (deferred) | quality_alpha proposal: LOW→MID floor; quality_plus: MID also gets best-of-N |

### Quality scoring (Combined Reviewer)
| Version | Change |
|---------|--------|
| pre-2.5 | Binary PASS/FAIL |
| v2.5.x | P4: 0.0–1.0 SPEC_SCORE + QUALITY_SCORE; PASS/WARN/FAIL tier |
| v2.7 (deferred) | Threshold raise (0.92 / 0.85) for quality mode |

### Hooks / safety
| Version | Change |
|---------|--------|
| pre-2.5 | Manual orchestrator-enforced gates |
| v2.5.x | P1: Native PostToolUse + SubagentStop hooks for debug-artifact scan and STATUS sanity |

### Plan validation
| Version | Change |
|---------|--------|
| v2.5.x | P3 Plan Reviewer preflight (mechanical audit before Phase 1) |

### Parallel dispatch
| Version | Change |
|---------|--------|
| v2.4.0 | Sequential per task |
| v2.5.x → v2.6.0 | P2: Wave-parallel sub-worktrees for independent tasks within a wave |

### Evaluation harness
| Version | Change |
|---------|--------|
| v2.5.x | P6: `evals/` directory, fixtures 01–07, judge.md, run.sh, baselines/ |
| v2.6.0 | Harness stabilization: Fix A/B, isolation, worktree-path coverage |
| **v2.7 (recommended to ship even though experiment closed)** | `evals/rubric.py` — deterministic correctness measurement (replaces LLM stochastic estimation for mechanical axes); `evals/judge.md` updated to consume rubric_results; `evals/run.sh` auto-invokes rubric.py; fixture 08 added as regression test for "repeated unit" miss; `evals/calibration/` framework for judge sanity checks before relying on them |

### state.json schema
| Version | Change |
|---------|--------|
| v2 schema | Foundational fields: tasks, baseline, risk_levels, compaction_points, execution_plan, quality_trend, spec_edits |
| v2.5.x | Added P4 quality_trend, P5 task_complexity |
| v2.6.0 | execution_plan with wave/parallel_group structure |
| v2.7 (deferred) | Would have added: mode, per-task bestofn block |

---

## §3 Experiments (closed and open)

Each significant experiment gets its own subdirectory under `docs/experiments/`
with JOURNAL + decisions/ + findings/. Index:

| Experiment | Status | Outcome | Path |
|------------|--------|---------|------|
| v2.7-quality-mode | CLOSED | Negative on quality_plus; positive on rubric infra | `docs/experiments/v2.7-quality-mode/` |
| v2.8-learning-log | In progress | Per-run sharded learning log + review-side Skill calls | `docs/experiments/v2.8-learning-log/` |
| (future) | | | `docs/experiments/v2.X-<name>/` |

See `docs/experiments/README.md` for the experiment template and protocol.

---

## How to read this file vs. other artifacts

- **`SKILL.md` frontmatter `metadata.version`** — current shipped skill version. Single source of truth for "what version is this right now."
- **`ARCHITECTURE.md`** — synthesized current-state view of how the skill works. Update whenever behavior changes (see its §13).
- **`skills/README.md`** — Archive-level index for currently installed
  standalone executor skills.
- **`HISTORY.md` (this file)** — skill-level narrative history. Both timeline and topic axes. Update when shipping a new version.
- **`DESIGN-v<X>.md`** — point-in-time design doc for a specific version's design intent. Frozen artifact.
- **`docs/experiments/<name>/`** — per-experiment record. Created at experiment start, finalized at close-out.
