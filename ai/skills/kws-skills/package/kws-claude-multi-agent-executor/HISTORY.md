# Skill History — kws-claude-multi-agent-executor

A two-axis summary of where this skill came from and what changed:

- **§1 Version timeline** — chronological version notes
- **§2 Improvement areas** — grouped by topic, with which versions touched each

Source of truth for skill behavior: `SKILL.md` (current version in frontmatter).
This file is for *humans navigating the history*.

Update protocol: see `AGENTS.md` ("Experiment & history record-keeping").

---

## §1 Version timeline

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
- Skill added to plugin manifest

### Earlier — see `kws-skills/CHANGELOG.md` at plugin level

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
| (future) | | | `docs/experiments/v2.X-<name>/` |

See `docs/experiments/README.md` for the experiment template and protocol.

---

## How to read this file vs. CHANGELOG vs. SKILL.md frontmatter

- **`SKILL.md` frontmatter `metadata.version`** — current shipped skill version. Single source of truth for "what version is this right now."
- **`kws-skills/CHANGELOG.md`** — plugin-level changelog. Tracks the package manifest version (not skill version). User-facing release notes.
- **`HISTORY.md` (this file)** — skill-level narrative history. Both timeline and topic axes. Update when shipping a new version.
- **`DESIGN-v<X>.md`** — point-in-time design doc for a specific version's design intent. Frozen artifact.
- **`docs/experiments/<name>/`** — per-experiment record. Created at experiment start, finalized at close-out.
