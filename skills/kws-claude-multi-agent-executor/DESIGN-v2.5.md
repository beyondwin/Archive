# Design: kws-claude-multi-agent-executor v2.5

Status: Draft (2026-05-13)
Author: kws + Claude Opus 4.7
Supersedes: none (additive to v2.4.0)
Source of evidence: GitHub research (see References at bottom)

## Background

v2.4.0 implements Anthropic's canonical orchestrator-worker pattern (Opus lead + Sonnet workers), git worktree isolation, state.json external memory, and risk-tiered verification. Web research against Anthropic's own multi-agent research blog, Claude Code Agent Teams docs, and 5 open-source equivalents (ccswarm, claude-flow/ruflo, wshobson/agents, BMAD-METHOD, ComposioHQ/agent-orchestrator) confirms the architecture is sound. This document specifies 6 incremental improvements (P1–P6) that close the gap to industry best practice without rewriting the existing skill.

### Scope decisions

- **Not changing**: orchestrator-worker pattern, Sonnet sub-agent dispatch, state.json schema (additive only), worktree isolation, risk-tiered verification.
- **Adopting**: native Claude Code hooks for gate enforcement (P1), parallel dispatch for independent tasks (P2), plan-quality preflight (P3), Generator-Verifier scoring (P4), effort scaling rules in Implementer prompts (P5), evaluation suite for regression detection (P6).
- **Rejecting**: ruvnet/claude-flow's swarm/queen model (over-engineered for ≤25-task plans), wshobson/agents' 100+ specialized sub-agent catalog (over-specialization), full Agent Teams replacement (experimental, no session resumption).

### Known limitation surfaced honestly

Anthropic explicitly notes multi-agent is *"less effective for tightly interdependent tasks such as coding"*. v2.5 mitigates via sequential per-task default + dependency graph + task_summaries handoff, but does not eliminate the limitation. The skill's `description` field and `## Limitations` section MUST state: *"single-session execution is preferable for ≤5-task plans or plans with deep cross-task coupling."*

---

## P1 — Native hooks for gate enforcement

### Problem

Currently the Orchestrator manually runs the debug-artifact scan (Phase 1 Step 4.1) and the cleanup grep. If the Orchestrator's loop accidentally skips Step 4.1 — through context drift, a malformed sub-agent reply, or future refactor — the gate is silently bypassed. Discipline lives in prose, not in the runtime.

### Design

Use Claude Code's `SubagentStop` and `PostToolUse` hooks, registered in the worktree's `.claude/settings.json` (already created at Phase 0 Step 2.5 for safety blocks). Hooks are runtime-enforced; they cannot be skipped by orchestrator misbehavior.

**Hook 1 — Debug artifact scan (`PostToolUse` on `Edit|Write`):**

Triggers after any Implementer Edit/Write. Greps the just-changed line for `console\.log|TODO|FIXME|debugger`. On hit: returns exit code 2 with a structured rejection message that the Implementer sees as a system error — it auto-retries the edit. No re-dispatch needed.

**Hook 2 — STATUS sanity check (`SubagentStop`):**

Fires when an Implementer sub-agent finishes. Reads the sub-agent's stdout summary (Agent tool result is passed via `$CLAUDE_TOOL_RESULT`). Checks: contains `STATUS: DONE` OR `STATUS: ESCALATE`; contains `COMMIT:` if `DONE`; contains `FILES_CHANGED:`. On any missing field → exit 2 with diagnostic. Orchestrator receives the failure and re-dispatches as if Reviewer FAIL.

### Implementation

Extend Phase 0 Step 2.5 settings.json (the existing safety-hooks file):

```json
{
  "hooks": {
    "PreToolUse": [...existing rm/push/drop blocks...],
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "<worktree>/.orchestrator/hooks/scan-debug-artifacts.sh"
      }]
    }],
    "SubagentStop": [{
      "hooks": [{
        "type": "command",
        "command": "<worktree>/.orchestrator/hooks/check-implementer-output.sh"
      }]
    }]
  }
}
```

Two helper scripts, ~30 lines each, materialized at Phase 0 Step 2.5 via the Write tool.

### Files affected

- `SKILL.md` Phase 0 Step 2.5 — extend settings.json template, add helper-script Write steps
- New: `references/hooks/scan-debug-artifacts.sh.template`
- New: `references/hooks/check-implementer-output.sh.template`
- Phase 1 Step 4.1 — DELETE the manual artifact scan (now enforced by hook)
- Guardrails table — replace *"debug artifact scan is orchestrator's responsibility"* row with *"debug artifact scan is hook-enforced"*

### Risks

- Hook misfire on legitimate uses of `TODO` (e.g., inside a string literal). Mitigation: scan only `^+` diff lines AND exclude lines inside `"..."` / `'...'` / triple-backtick blocks. Worst case: false positive forces Implementer to phrase it differently — annoying but not catastrophic.
- `$CLAUDE_TOOL_RESULT` payload format may change. Mitigation: the check script is small and easy to update; pin Claude Code version in plugin metadata.

### Acceptance criteria

1. Implementer that commits `console.log("debug")` is auto-rejected without orchestrator intervention.
2. Implementer that returns malformed output (missing `COMMIT:`) is auto-rejected.
3. Orchestrator's Phase 1 Step 4.1 grep can be deleted; behavior remains identical for both pass and fail cases.

---

## P2 — Parallel dispatch for independent task waves

### Problem

Current execution is strictly sequential: Task 0 must complete before Task 1 starts, even if Task 1 has `deps=[]` (no dependency on Task 0). Anthropic Research reports parallel tool calling *"cut research time by up to 90% for complex queries"*. For 10+ task plans with 2–3 independent waves, the wall-time savings are substantial.

### Design

**Wave identification (Phase 0 Step 6):**

After the dependency graph is built, compute waves greedily:
- Wave 0 = all tasks with `deps == []`
- Wave N = all tasks whose deps are all in waves 0..N-1
- Tasks within a wave have no inter-dependency by construction.

But two tasks in the same wave may still share a file. Refine:
- Within a wave, group tasks by *shared-file partition*: tasks with disjoint `files` sets can run parallel; tasks with file overlap must serialize.

Result: each wave becomes a list of *parallel groups*. Most plans yield wave sizes of 1–3 in practice.

**Parallel Implementer dispatch (Phase 1 modification):**

When the current wave has a parallel group with >1 task:
1. Create a **sub-worktree per parallel task**: `<worktree>/.parallel/task_<N>` is a separate `git worktree add` off the current HEAD.
2. In one Orchestrator message, issue N `Agent` tool calls in parallel — each Implementer runs in its sub-worktree with the same prompt template, just different task.
3. Collect all N results. For each `STATUS: DONE`: cherry-pick its commit onto the main worktree (sequentially, to keep clean linear history). For each `ESCALATE`: handle one at a time via standard Escalation Protocol.
4. Combined Reviewer + Verifier run **sequentially after merge** (not in parallel) — they need the merged state.

**Failure handling:**

If any parallel Implementer fails: the sub-worktree is discarded (`git worktree remove --force`); main worktree state is unaffected. Re-dispatch the failed task only (the others' commits remain).

### Implementation

- Phase 0 Step 6 — add wave + parallel-group computation. Write to `state.execution_plan` (new field): `[{wave: 0, parallel_groups: [[1, 3], [2]]}, {wave: 1, parallel_groups: [[4]]}]`
- Phase 1 — new substep before Step 1: "Check current task's parallel group. If group size = 1: standard flow. If > 1: parallel sub-flow."
- Parallel sub-flow: ~40 lines of new procedure (sub-worktree create, dispatch, merge, cleanup).
- New guardrail: *"Parallel Implementer outputs must produce non-overlapping FILES_CHANGED. If a parallel Implementer touches a file outside its task's declared Files: block AND that file is also touched by another parallel task: halt and serialize the wave."*

### Files affected

- `SKILL.md` Phase 0 Step 6, Phase 1 (new substep)
- New state.json field: `execution_plan`
- Guardrails table — 1 new row

### Risks

- **Merge conflicts during cherry-pick.** Mitigation: the partition guarantees disjoint files at the Files: declaration level. If an Implementer secretly edits a file outside its declared scope, the new guardrail catches it pre-merge.
- **state.json concurrent writes.** Mitigation: sub-worktrees write to their own `.parallel/task_<N>/.orchestrator/local.json`; the Orchestrator (main worktree) is the sole writer of the canonical state.json — it aggregates after collection.
- **Sub-worktree disk overhead.** Mitigation: cleaned up immediately after wave completion. Peak overhead = parallel group size × git checkout size.
- **Sub-agent contention for the same external resource (DB port, file lock).** Mitigation: not solved by this design. Document as a known limitation; recommend user marks such tasks with explicit `serial` flag in plan.

### Acceptance criteria

1. A test plan with 4 independent tasks completes in wall-time approximately equal to the slowest single task, not the sum.
2. A test plan with no independent tasks falls back to sequential with zero overhead.
3. A parallel task that touches a file outside its declared Files: block is rejected before merge with a clear error.

---

## P3 — Plan-quality preflight (Plan Reviewer sub-agent)

### Problem

Phase 0.5 Ambiguity Gate is reactive — it only catches missing Files blocks and out-of-repo paths. Many other plan defects (missing acceptance criteria, inter-task contract mismatch, vague task descriptions) only surface at runtime via SPEC_BLOCKER escalations. Each escalation costs one Implementer dispatch + reset + re-dispatch (~2–3 minutes wall-time + tokens).

BMAD-METHOD's central insight: *dedicated planning roles BEFORE dev*. We don't need full BMAD planning — we need a one-shot pre-flight reviewer.

### Design

New Phase 0 Step 0.6 — **Plan Reviewer** sub-agent, dispatched once before Phase 1 begins.

**Plan Reviewer prompt** (`references/plan-reviewer-prompt.md`):

Reviews the Plan + Spec against this rubric:
1. Every `### Task N:` has a `**Files:**` block — already covered by 0.5, but re-verify.
2. Every task has either an `## Acceptance Criteria` shell block OR is explicitly marked LOW with no AC. Tasks with neither: flag.
3. Cross-task contract consistency: if Task A declares it produces function `foo(x: int) -> bool` (in spec) and Task B declares it consumes `foo`, signatures must match.
4. Spec terminology consistency: same concept named consistently across spec sections.
5. Task ordering vs declared dependencies: dependency graph (parsed from task descriptions) should be acyclic and topologically consistent with task numbering.

**Output schema:**

```json
{
  "status": "PASS | ISSUES_FOUND",
  "issues": [
    {"severity": "BLOCKER | WARN", "task": "<id or 'all'>", "category": "missing_ac | contract_mismatch | naming_drift | dep_inconsistency", "description": "<one sentence>", "suggested_fix": "<one sentence>"}
  ]
}
```

**Orchestrator response:**

- All `WARN`: log to state.json `plan_review_warnings`; proceed.
- Any `BLOCKER`: present a single batched question to the user — "Plan Reviewer found N blockers. Show all and halt for manual fix, OR (if user pre-approved auto-clarify mode) Orchestrator edits plan/spec per `suggested_fix` and re-runs Plan Reviewer (max 2 cycles)."

### Implementation

- New `references/plan-reviewer-prompt.md` (~80 lines)
- `SKILL.md` Phase 0 — new Step 0.6 between 0.5 and 1
- `state.json` — add `plan_review_warnings: []` field
- Pre-flight is OPTIONAL via arg `preflight=off` for users who trust their plans (e.g., regression runs of already-validated plans).

### Files affected

- `SKILL.md` Phase 0 (new step)
- New: `references/plan-reviewer-prompt.md`
- `state.json` schema (additive)

### Risks

- **Plan Reviewer is itself a sub-agent → can hallucinate issues.** Mitigation: rubric is mechanical (presence/absence checks, not subjective). Reviewer prompt explicitly says: "do not flag style preferences or non-mechanical issues."
- **Cost of 1 extra sub-agent dispatch** (~30s wall-time, ~5k tokens). Net: cheap insurance.

### Acceptance criteria

1. A plan with a missing AC block on a HIGH-risk task is flagged as BLOCKER pre-flight.
2. A plan where Task 3 produces `foo()` and Task 5 calls `foo(x, y)` (wrong arity) is flagged.
3. A plan that passes preflight runs Phase 1 with at most 1 SPEC_BLOCKER escalation across all tasks on average (measured by P6 evals).

---

## P4 — Generator-Verifier scoring (0.0–1.0)

### Problem

Combined Reviewer output is binary `PASS/FAIL`. This loses signal:
- A `PASS` at 0.7 quality is different from a `PASS` at 0.95.
- Small regressions in code quality across a long run aren't visible.
- No way to tune the retry threshold (currently always retry on FAIL, never retry on borderline PASS).

Anthropic Multi-Agent Research: *"single LLM call outputting 0.0-1.0 scores proved most consistent with human judgment"*.

### Design

**Reviewer output additions:**

```
SPEC_SCORE:    0.0-1.0
QUALITY_SCORE: 0.0-1.0
SPEC_STATUS:   PASS | FAIL   (derived: PASS iff SPEC_SCORE >= 0.85)
QUALITY_STATUS: PASS | FAIL  (derived: PASS iff QUALITY_SCORE >= 0.75)
```

Scores are integer-quantized to 1 decimal (0.0, 0.1, ..., 1.0) to reduce calibration noise.

**Three tiers** (instead of binary PASS/FAIL):

| Tier | Condition | Orchestrator action |
|------|-----------|---------------------|
| PASS | Both scores ≥ threshold | Proceed to Verifier |
| WARN | Either score in [threshold − 0.15, threshold) | Proceed to Verifier; record `quality_score` + issues in `task_summaries.warnings` |
| FAIL | Either score < threshold − 0.15 | Standard FAIL retry flow |

**Trend tracking:**

`state.json.quality_trend` = rolling array of last 10 task scores. If mean drops > 0.1 across 5 consecutive tasks: surface to user at next compaction point. ("Quality trending down: tasks 8-12 averaged 0.78 vs first 5 tasks at 0.91. Consider review.")

### Implementation

- `references/reviewer-prompt.md` — extend output schema with scores, add scoring rubric ("0.95 = textbook-quality; 0.75 = ships but has minor issues; 0.5 = significant problems"). ~15 lines.
- `SKILL.md` Phase 1 Step 2 — branch on tier (3 cases instead of 2).
- `state.json` — add `quality_trend` array, per-task `quality_score`, per-task `spec_score`.
- Guardrail: *"Score thresholds are not user-configurable in v2.5 — defaults (0.85 spec, 0.75 quality) are calibrated against the evaluation suite."*

### Files affected

- `references/reviewer-prompt.md`
- `SKILL.md` Phase 1 Step 2, state.json schema
- New guardrail row

### Risks

- **Score calibration drift across Sonnet versions.** Mitigation: P6 eval suite measures judge consistency; thresholds re-tuned per Claude version.
- **WARN tier could become a hiding place for low-quality work.** Mitigation: surface WARN count in Final Summary Report; user sees pattern.

### Acceptance criteria

1. A trivial typo fix scores `quality_score >= 0.9`.
2. A correctly-implemented feature with poor naming/structure scores in 0.65–0.80 range, lands in WARN, proceeds.
3. A wrong implementation scores < 0.6, lands in FAIL, retries.

---

## P5 — Effort scaling rules in Implementer prompts

### Problem

Anthropic Research: *"Agents struggle to judge appropriate effort for different tasks, so the team embedded scaling rules in the prompts."* Currently every Implementer dispatch uses the same template regardless of task complexity. A trivial alias rename gets the same "use systematic-debugging skill, run TDD, etc." preamble as a complex multi-file refactor — leading to over-engineering of small tasks.

### Design

**Task complexity estimation (Phase 0 Step 6 extension):**

For each task, compute a complexity score from:
- File count in `**Files:**` block
- Estimated LOC change (heuristic: spec excerpt length × 0.5)
- Number of new functions/types declared in spec
- Risk level (LOW=1, MID=2, HIGH=3 multiplier)

Quantize to 3 buckets: SMALL / MEDIUM / LARGE.

| Bucket | Heuristic | Implementer guidance |
|--------|-----------|----------------------|
| SMALL | 1 file + <30 LOC + risk LOW | "aim for ≤8 tool calls; skip TDD for trivial renames/aliases unless task explicitly says test required" |
| MEDIUM | 2-3 files + <150 LOC | "aim for 10-25 tool calls; TDD recommended" |
| LARGE | 4+ files OR risk HIGH | "aim for 25-60 tool calls; TDD required; consider splitting if you exceed 60" |

**Prompt injection:**

`{task_size}` and `{effort_guidance}` placeholders added to `references/implementer-prompt.md`. The Required Skills section's TDD trigger softens for SMALL tasks: "*if your task involves writing new logic with test coverage AND task_size is MEDIUM or LARGE*".

### Implementation

- `references/implementer-prompt.md` — extend with `{task_size}` and `{effort_guidance}` placeholders. ~10 lines.
- `SKILL.md` Phase 0 Step 6 — add complexity estimation procedure.
- `SKILL.md` Phase 1 Step 1 — fill in the new placeholders from Phase 0 output.
- `state.json` — add `task_complexity: {task_N: "SMALL|MEDIUM|LARGE"}`.

### Files affected

- `references/implementer-prompt.md`
- `SKILL.md` Phase 0 Step 6, Phase 1 Step 1
- state.json schema (additive)

### Risks

- **Mis-estimation:** a "small" task with hidden complexity gets under-instructed. Mitigation: heuristic biases upward (risk-level multiplier). Downside is mild (slight over-engineering on edge cases), not catastrophic.
- **TDD skip on SMALL:** could ship untested trivial bugs. Mitigation: existing Combined Reviewer still flags missing test coverage as a QUALITY_ISSUE. Verifier (for MID/HIGH) still runs.

### Acceptance criteria

1. A 5-line typo fix task results in Implementer using ≤5 tool calls (vs. current ~15).
2. A 4-file refactor task gets the LARGE template, takes appropriate time.
3. Wall-time on a representative 15-task plan with mixed sizes drops ≥15% vs v2.4.0.

---

## P6 — Evaluation suite for regression detection

### Problem

The skill has no automated regression test. Every patch (R13–R16, prompt edits) is shipped on trust. Anthropic's guidance: *"Start with 20-query test sets... effect sizes this large, you can spot changes with just a few test cases."* We don't need 20; we need 5–8 representative fixtures and a judge.

### Design

```
ai/skills/kws-skills/package/kws-claude-multi-agent-executor/
├── SKILL.md
├── references/...
└── evals/
    ├── fixtures/
    │   ├── 01-trivial-typo.yaml         # 1 task, SMALL
    │   ├── 02-three-file-refactor.yaml  # 3 tasks, MEDIUM
    │   ├── 03-add-new-feature.yaml      # 5 tasks, mixed
    │   ├── 04-cross-plan-handoff.yaml   # 2 plans, MEDIUM each
    │   ├── 05-ambiguous-spec.yaml       # tests Plan Reviewer + escalation paths
    │   ├── 06-flaky-test-recovery.yaml  # tests Verifier retry + ENV_BLOCKER triage
    │   └── 07-low-batch-heavy.yaml      # 6 LOW tasks → batch verify path
    ├── judge.md                          # LLM-as-judge prompt template
    ├── run.sh                            # run + score harness
    └── baselines/                        # per-version scored results
        ├── v2.4.0.json
        ├── v2.5.0.json
        └── ...
```

**Fixture format:**

Each `.yaml` describes the plan, spec, repo bootstrap commands (set up a temp git repo with the expected initial state), and "ground truth" expected outcomes (commits expected, files modified, tests that should pass).

**Run harness (`run.sh`):**

For each fixture:
1. `git init` a fresh temp directory; apply fixture's bootstrap.
2. Invoke the skill via `claude -p ...` headless.
3. Capture: wall-time, total token usage (from `--output-format stream-json`), task statuses, commit count, test results.
4. Run `judge.md` against the captured run to score: *correctness*, *spec compliance*, *code quality*, *cost efficiency*.
5. Write to `baselines/v<X.Y.Z>.json`.

**Comparison:**

```bash
./evals/run.sh                  # produce current baseline
diff baselines/v2.4.0.json baselines/v2.5.0.json   # see deltas
```

Regression detector: if any fixture's score drops > 0.1 across versions, flag.

### Implementation

- 7 fixtures (~50–100 lines each)
- 1 judge prompt (~60 lines)
- 1 harness script (~120 lines bash + jq)
- `SKILL.md` — no change. Eval suite is external.
- README.md in evals/ — usage instructions.

### Files affected

- New `evals/` directory (all-new content, no SKILL.md change)
- Optionally: GitHub Actions workflow to run evals on PR (out of scope for v2.5)

### Risks

- **Fixture-specific overfitting.** Mitigation: fixtures are diverse (different sizes, different failure modes); judge prompt evaluates against rubrics, not exact outputs.
- **Eval cost** (~$5–15 per full run on Sonnet pricing). Mitigation: don't run on every commit; run on version bumps and major refactors.

### Acceptance criteria

1. Running `./evals/run.sh` produces `baselines/v2.4.0.json` with all 7 fixtures scored ≥ 0.6 (current v2.4.0 quality).
2. v2.5.0's baseline shows score deltas with explanations matching the P1–P5 design intents (e.g., parallel dispatch reduces wall-time on fixture 03).
3. Any fixture that regresses > 0.1 between versions blocks merge.

---

## Sequencing

| Tier | Items | Rationale |
|------|-------|-----------|
| **T1 (do first)** | P1 (hooks), P3 (preflight) | Highest ROI; low coupling to existing code; both are additive enforcement layers. Combined ~1 day of work. |
| **T2 (next)** | P5 (effort scaling), P4 (scoring) | Both modify existing templates only; no new sub-agent types. Combined ~1 day. |
| **T3 (when needed)** | P2 (parallel dispatch) | Highest complexity; only valuable for plans with ≥10 tasks and ≥3 independent waves. Defer until a real plan benefits. |
| **T4 (infrastructure)** | P6 (evals) | Should land BEFORE T2 in an ideal world (so T2 can be measured), but takes longest. Realistically: build evals against v2.4.0 baseline first (no code change), then validate T1+T2+T3 deltas with them. |

**Recommended order**: P6 (build evals against v2.4.0) → P1, P3 (T1 patch) → re-eval → P5, P4 (T2 patch) → re-eval → P2 (only if evidence warrants).

## Version plan

- **v2.5.0**: T1 (P1 + P3) — hooks + preflight. Bump version, ship.
- **v2.5.1**: T2 (P4 + P5) — scoring + effort. Minor version (additive prompt-template change only).
- **v2.6.0**: P2 (parallel dispatch). Major because state.json schema gains `execution_plan` field and Phase 1 control flow changes.
- **v2.5.x**: P6 (evals) — versionless infrastructure; lands once and evolves with each release.

## Open questions

1. **Should the SubagentStop hook be skill-scoped or worktree-scoped?** Worktree-scoped (current proposal) only affects sub-agents that operate within the worktree. Skill-scoped would require plugin-level hook registration, which is broader and possibly leakier. Default: worktree-scoped.

2. **For P2 parallel dispatch, do we need per-sub-worktree safety hooks** (replicating `.claude/settings.json`)? Current proposal: yes — copy the same settings.json into each sub-worktree. Cheap to do, prevents the same `rm -rf /` etc. attacks in parallel paths.

3. **For P4 scoring, do we expose scores in `task_summaries` for downstream tasks to read?** Pro: a downstream Implementer could lower confidence in upstream task's contracts if upstream's quality_score was 0.7. Con: introduces fragile self-reflection loop. Default: NO for v2.5; revisit if real signal emerges.

4. **For P6 evals, should the judge be Opus or Sonnet?** Anthropic Research uses LLM-as-judge with single-call 0.0–1.0 scoring. Opus is more reliable on calibration but 5× cost. Default: Sonnet, with Opus as a manual second-opinion when score deltas are borderline.

## Non-goals for v2.5

- Full Claude Code Agent Teams adoption (experimental, no resumption)
- Async sub-agent execution (canonical industry gap; Anthropic itself hasn't solved this)
- Self-learning memory / federated comms (claude-flow-style; over-engineered for our scope)
- 100+ specialized sub-agent catalog (wshobson/agents style; over-specialized)
- Replacing state.json with a SQLite/embedded DB (premature optimization; flat JSON is fine at this scale)

## References

1. [How we built our multi-agent research system — Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system) — orchestrator-worker canonical, 15× token cost, "less effective for coding" warning, external memory pattern.
2. [Multi-agent coordination patterns — Claude](https://claude.com/blog/multi-agent-coordination-patterns) — 5 patterns including Generator-Verifier (P4 basis).
3. [Building effective agents — Anthropic](https://www.anthropic.com/research/building-effective-agents) — foundational pattern reference.
4. [Orchestrate teams of Claude Code sessions — Agent Teams docs](https://code.claude.com/docs/en/agent-teams) — native hooks (TaskCreated/TaskCompleted/TeammateIdle) inspiration for P1; resumption limitation that keeps us off the full Agent Teams path.
5. [nwiizo/ccswarm](https://github.com/nwiizo/ccswarm) — git worktree per agent (we match), channel-based coordination (we don't need), explicit "Parallel Executor Not wired" caveat.
6. [ruvnet/claude-flow / ruflo](https://github.com/ruvnet/claude-flow) — swarm/queen architecture (rejected as over-engineered for our scope).
7. [wshobson/agents](https://github.com/wshobson/agents) — 100+ specialized sub-agent catalog (rejected; our 4 roles suffice).
8. [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) — planning roles (Analyst, PM, Architect) before dev → P3 Plan Reviewer inspiration.
9. [ComposioHQ/agent-orchestrator](https://github.com/ComposioHQ/agent-orchestrator) — parallel coding agents with worktree-per-agent and PR-per-agent → P2 sub-worktree pattern.

## Changelog

- 2026-05-13: Initial draft, status Draft. Awaiting kws review.
