# Architecture — kws-claude-multi-agent-executor

How this skill works, top to bottom. For runtime instructions see `SKILL.md`.
For version history see `HISTORY.md`. For experiment records see
`docs/experiments/`.

**When to update this file**: see [§13 Update protocol](#13-update-protocol).

---

## 1. What the skill does

Takes a plan document + spec document as input, then **autonomously** executes
every task in the plan from start to finish. The user doesn't approve between
tasks. The skill drives the entire delivery cycle: write code, review code,
verify tests, update docs, repeat.

Inputs:
- `plan=<path>` — markdown plan with `### Task N:` sections, each declaring
  `**Files:**` and optionally `## Acceptance Criteria`
- `spec=<path>` — design spec the implementation must match
- Optional: `risk=low|mid|high` (override per-task risk), `docs_scope=...`

Output: a sequence of commits on an isolated worktree, plus a final summary
report. The main branch is never modified during execution.

## 2. The Orchestrator-Worker pattern

Anthropic's canonical multi-agent topology. One Opus orchestrator drives
many fresh Sonnet sub-agents.

```
                Opus Orchestrator (single session)
                      │
   ┌─────┬────────────┼─────────────┬──────────────┐
   │     │            │             │              │
 Plan   Implementer  Combined    Verifier       Docs Updater
 Reviewer (Sonnet,   Reviewer    (Sonnet,        (Sonnet,
 (Sonnet, fresh)     (Sonnet,    headless)       headless)
 preflight)          fresh)
                      │
                state.json (external memory)
                git worktree (isolated workspace)
```

**Why orchestrator-worker, not other topologies:**
- Single-session orchestrator can run 50+ task plans without running out
  of context, because sub-agents return *summaries* — the orchestrator
  never accumulates raw work in its own buffer.
- Fresh sub-agents start with no priors → less drift, more determinism per
  task.
- Sub-agents that misbehave (escalation, malformed output) are caught at
  the orchestrator boundary, never poisoning future tasks.

**What the orchestrator never does**: it never writes code itself. It
reads, decides, dispatches, parses results, updates state. The pattern is
"manager, not contributor."

## 3. Lifecycle: 3 phases

### Phase 0 — Setup (once)

1. Parse invocation arguments (`plan=`, `spec=`, `risk=`, `docs_scope=`,
   experimental `mode=`).
2. Check the tree is clean (`git status` empty); halt if not.
3. Create the work-isolation **worktree** at `<repo>/../worktrees/<branch>`.
   All subsequent work happens here; `main` stays untouched.
4. Install **safety hooks** into `<worktree>/.claude/settings.json`:
   - `PreToolUse` blocks for `rm -rf`, `git push`, schema drops
   - `PostToolUse` scan for debug artifacts (`console.log`, `TODO`,
     `FIXME`, `debugger`) on Edit/Write
   - `SubagentStop` sanity check on Implementer output structure
5. Read plan + spec. Run the **Ambiguity Gate**: detect missing Files
   blocks, out-of-repo paths, contradictions. Halt for user clarification
   if any.
6. Assign **risk tiers** (LOW/MID/HIGH) per task (see §7).
7. Snapshot **baseline test state** (pass/fail counts of current test
   suite) for later regression comparison.
8. Compute **compaction points** — task indices after which earlier
   raw context can be dropped from orchestrator memory.
9. Compute **wave structure** (P2) — group tasks by dependency. Within
   a wave, tasks with non-overlapping file sets can run in parallel
   sub-worktrees.
10. Compute **effort buckets** (P5) per task — SMALL/MEDIUM/LARGE based
    on file count, LOC estimate, declarations, risk.
11. Run **Plan Reviewer preflight** (P3) — a headless Sonnet sub-agent
    that mechanically audits the plan for missing AC blocks, contract
    mismatches, dependency inconsistencies.
12. Initialize `state.json` with all the computed metadata.

### Phase 1 — Per-task cycle (repeated)

For each task in `state.execution_plan`:

```
Step 1: Dispatch Implementer (Sonnet, fresh)
   │  Prompt: spec excerpt, files, risk, effort_guidance,
   │          previous_issues (if retry)
   ↓ STATUS: DONE | ESCALATE
   
Step 2: Dispatch Combined Reviewer (Sonnet, fresh)
   │  Inputs: spec, diff, previous_issues
   │  Outputs: SPEC_SCORE, QUALITY_SCORE (0.0-1.0), SPEC_FAULT
   ↓ tier:
   │  PASS  (≥0.85 spec AND ≥0.75 quality) → Step 3
   │  WARN  (≥0.70 AND ≥0.60)             → Step 3 + record warnings
   │  FAIL                                  → branch:
   │     spec_contradicts → spec edit branch (P15)
   │     unclear          → clarification (no spec text change)
   │     implementer_omitted/none → standard retry (max 3)
   ↓
Step 3: Verifier (MID/HIGH only — LOW batched at compaction points)
   │  headless `claude -p` → JSON result file
   │  Runs full test suite, compares to baseline
   ↓ result:
   │  PASS                → Step 4
   │  FAIL (test broke)   → retry (max 3)
   │  ENV_BLOCKER         → ESCALATE to user
   ↓
Step 4: Agent Cleanup
   │  Debug artifact scan (now hook-enforced per P1)
   │  Protected-file check (no edits to .git, .orchestrator, ...)
   │  Commit verification
   ↓
   Advance to next task. Update state.json.
```

**Parallel sub-flow (P2)**: when a wave has multiple tasks in the same
parallel group, each runs in its own sub-worktree
(`<worktree>/.parallel/task_N`). After all DONE: cherry-pick winning
commits to the main worktree, then run Reviewer + Verifier sequentially
on the merged state.

**LOW task batching**: LOW tasks skip per-task Verifier. They accumulate
in `state.low_tasks_pending_verification`. At each compaction point and
at Phase 2 entry, the batch Verifier runs all accumulated LOW tasks at
once. If batch FAIL: bisect to identify offending task, reset, retry.

### Phase 2 — Cleanup (once at end)

1. **Batch Verifier sweep** — verify any remaining LOW tasks.
2. **Final Docs Updater** — headless Sonnet, given the consolidated
   `FILES_CHANGED` across all tasks, updates README, CHANGELOG, related
   docs.
3. **Final Summary Report** — markdown summary delivered to the user:
   tasks done/skipped, WARN list, quality_trend chart, total wall time,
   total tokens, spec edits made.

## 4. Sub-agent roles (catalog)

| Role | Model | Dispatch | When | Output format |
|------|-------|----------|------|---------------|
| Plan Reviewer | Sonnet | headless | Phase 0 Step 0.6, once | JSON: `{status, issues[]}` |
| Implementer | Sonnet | `Agent` tool (fresh) | Phase 1 Step 1, per task | Text: `STATUS:`, `COMMIT:`, `FILES_CHANGED:`, `FILES_TEST_CHANGED:` |
| Combined Reviewer | Sonnet | `Agent` tool (fresh) | Phase 1 Step 2, per task | Text: `SPEC_SCORE:`, `QUALITY_SCORE:`, `SPEC_FAULT:`, `ISSUES:` |
| Verifier | Sonnet | headless `claude -p` | Phase 1 Step 3 (MID/HIGH) + Phase 2 batch (LOW) | JSON: test results, regression list, environment status |
| Phase Docs Updater | Sonnet | headless `claude -p` | Compaction points | Markdown summary + commit |
| Final Docs Updater | Sonnet | headless `claude -p` | Phase 2 Step 1 | Markdown summary + commit |

**`Agent` tool vs headless `claude -p`**:
- `Agent` returns result into orchestrator's context — good for interactive
  back-and-forth tasks where the orchestrator needs to read the structured
  reply directly.
- `claude -p` writes to a JSON file — good when the result is bulky
  (test output, doc text) and the orchestrator only needs the verdict.
  Avoids context bloat.

## 5. State management (external memory)

`<worktree>/.orchestrator/state.json` is the **single source of truth**.
Every orchestrator decision: read state.json → compute → mutate → write.

Selected fields (full schema in `SKILL.md` Phase 0 Step 6):

```json
{
  "schema_version": "2",
  "branch": "...",
  "worktree": "...",
  "mode": "interactive_session | headless_pending | headless_running | ...",
  "active_plan": "plan1 | plan2",
  "tasks": {
    "0": {
      "status": "PENDING | IN_PROGRESS | COMPLETE | SKIPPED",
      "risk": "low | mid | high",
      "files": ["..."],
      "files_test": ["..."],
      "review_retries": 0,
      "verifier_retries": 0,
      "escalation_count": 0,
      "spec_score": 0.90,
      "quality_score": 0.85,
      "review_tier": "PASS",
      "commit": "abc1234",
      "spec_clarifications": 0
    }
  },
  "baseline": {"passing": 12, "failing": 0},
  "execution_plan": [
    {"wave": 0, "parallel_groups": [[1, 3], [2]]},
    ...
  ],
  "compaction_points": [4, 8, 12],
  "quality_trend": [0.9, 0.85, 0.95, ...],   // rolling last 10
  "low_tasks_pending_verification": [...],
  "task_summaries": {
    "task_N": {"summary": "...", "warnings": [...]}
  },
  "task_complexity": {"0": "SMALL", "1": "LARGE", ...},
  "spec_edits": [{"task", "spec_line", "reason", "commit", "ts", "fault"}],
  "plan_review_warnings": []
}
```

**Resumption**: because all state is in JSON, a fresh orchestrator session
can resume from any point by reading state.json and continuing at the
recorded task/step. This is how `mode: headless_pending` works — the
spawning session writes minimal state, the spawned session fills it in.

## 6. Isolation mechanisms

| Boundary | Mechanism |
|----------|-----------|
| Main branch ↔ skill execution | `git worktree` at `<repo>/../worktrees/<branch>` — separate working tree, no cross-contamination of working files |
| Parallel tasks within a wave | Sub-worktrees at `<worktree>/.parallel/task_N/` — each task runs in its own checkout |
| Orchestrator ↔ sub-agent context | Fresh sub-agent dispatch — Sonnet starts with no orchestrator priors; prompt carries only what it needs |
| Sub-agent ↔ destructive ops | `.claude/settings.json` hooks block `rm -rf`, `git push`, schema drops via `PreToolUse` regex |
| Sub-agent output validity | `SubagentStop` hook checks structure: `STATUS:` present, `COMMIT:` present if DONE, `FILES_CHANGED:` present. Malformed → orchestrator sees rejection, re-dispatches |
| Debug artifacts leaking into commits | `PostToolUse` hook scans diff lines for `console.log`/`TODO`/`FIXME`/`debugger` on Edit/Write |

## 7. Risk tiers

Assigned by orchestrator at Phase 0 Step 4. Controls verifier dispatch
timing, effort bucket eligibility, and (in proposed quality_plus) model
selection.

| Tier | Criteria | Verifier | Effort bucket eligibility |
|------|----------|----------|---------------------------|
| LOW  | 1 file, isolated module, no API change | Batched at compaction points | SMALL eligible (≤8 tool calls) |
| MID  | 2+ modules, shared state, config changes | Per-task | MEDIUM default (10–25 tool calls) |
| HIGH | DB/schema/API surface, breaking change, explicitly marked | Per-task | LARGE forced (25–60 tool calls) |

**LOW→MID auto-upgrade rule**: if a LOW task touches any file already
touched by an earlier LOW task in the same plan, the later task is
upgraded to MID. Prevents batch Verifier from accumulating overlapping
changes that hide which task broke what.

## 8. Quality scoring (P4)

Replaces binary PASS/FAIL. Combined Reviewer outputs `SPEC_SCORE` and
`QUALITY_SCORE`, both 0.0–1.0 quantized to one decimal.

**Tier mapping**:
- `PASS`: `SPEC_SCORE >= 0.85` AND `QUALITY_SCORE >= 0.75`
- `WARN`: (PASS not met) AND `SPEC_SCORE >= 0.70` AND `QUALITY_SCORE >= 0.60`
- `FAIL`: otherwise

**WARN tier exists to avoid burning a retry on borderline-but-shippable
work**. WARN tasks proceed (Verifier still runs); the QUALITY_ISSUES
are recorded in `state.task_summaries.task_N.warnings[]` and surfaced
in the Final Summary Report.

**Quality trend tracking**: rolling 10-task buffer in
`state.quality_trend`. If the mean of the last 5 drops > 0.10 below
the mean of the first 5 (within the buffer), the next compaction point
surfaces a warning to the user — quality is degrading.

## 9. Spec-edit branch (P15)

A Reviewer FAIL with `SPEC_FAULT: spec_contradicts` or `unclear` is
classified as **spec problem, not implementer problem**. Standard retry
would burn `review_retries` budget without progress because the spec
itself is broken.

Spec edit branch instead:
1. Increment `task.spec_clarifications` (separate counter from
   `review_retries`). Cap at 3 per task.
2. Orchestrator re-reads the affected spec section and makes the smallest
   possible edit.
3. Append edit to `state.spec_edits[]`: `{task, spec_line, reason,
   commit, ts, fault}`.
4. Identify downstream tasks that overlap the edited spec section.
   Inject a `## [SPEC UPDATED]` section into their next Implementer
   prompt.
5. Commit spec edit: `chore(<plan>): clarify spec line N for task M`.
6. Reset to pre-task SHA. Re-dispatch Implementer from clean state.

## 10. Eval harness

`evals/` is independent of `SKILL.md` — it tests the skill from outside.

```
evals/
├── fixtures/           # one YAML per scenario (plan + spec + bootstrap +
│   │                   #   expected outcome + rubric)
│   ├── 01-trivial-typo.yaml
│   ├── 02-three-file-refactor.yaml
│   ├── ...
│   └── 08-subtle-input-validation.yaml
├── rubric.py           # deterministic per-fixture rubric runner
├── judge.md            # LLM judge prompt template (4-axis scoring)
├── run.sh              # the harness: bootstrap repo, invoke skill, capture
│                       #   state/log/diff/test/rubric, build judge prompt,
│                       #   write baseline JSON
├── baselines/          # per-version scored results
│   └── v2.6.0.json
└── calibration/        # judge-calibration framework (added v2.7)
    ├── good_impl.py    # reference impls
    ├── broken_impl.py
    ├── run.py          # invoke judge × N reps, verify Δ≥0.2
    └── README.md
```

**Two measurement layers**:
1. **Programmatic rubric** (`rubric.py`) — if fixture has `expected.rubric`,
   shell-execute each check, count pass/fail. Deterministic. Used for
   `correctness` and `spec_compliance` axes.
2. **LLM judge** (`judge.md` → Sonnet/Opus) — scores `code_quality` and
   `cost_efficiency` (subjective). Receives rubric_results as input so
   correctness is not re-estimated.

**Why both**: the v2.7 experiment found LLM judge alone has high per-rep
variance (±0.16 on subjective axes) and gives fair partial credit that
dampens deltas. Splitting deterministic vs subjective measurement
eliminated noise on the mechanical axes.

## 11. Key design decisions (why this pattern)

| Decision | Why this, not alternatives |
|----------|----------------------------|
| Orchestrator-Worker (not swarm/queen) | Swarm requires complex emergent coordination. Orchestrator-Worker is well-understood, debuggable, resumable |
| Opus orchestrator + Sonnet workers (not all-Opus or all-Sonnet) | Orchestration needs Opus-level judgment (when to escalate, how to respond to FAIL). Implementation can use Sonnet — measurable on calibration |
| External memory (state.json) | Resumption, debuggability, cap on orchestrator context growth. SQLite would be over-engineered for the field set |
| `Agent` tool for short interactive sub-agents, headless `claude -p` for big outputs | Avoids orchestrator context bloat from bulky test logs / doc text |
| Worktree isolation (not branch-only) | Tests can run in the worktree without disturbing the user's main checkout. Hooks scoped to the worktree, not user-global |
| Risk tiers as blast-radius, not quality bar | TDD-always, Reviewer-always — quality bar is uniform. Risk decides verification timing/effort, not "how good must this be" |
| WARN tier (not just PASS/FAIL) | Without WARN, every borderline result burns a retry. With WARN, borderline work ships with a flag, retry budget reserved for true breaks |
| Sub-agents return summaries, not raw work | Orchestrator scales to 50+ tasks because per-task context is bounded |
| Deterministic rubric runner (v2.7) | LLM judge alone has Δ < 0.2 discrimination on close cases. rubric.py removes that noise from mechanical axes |
| Pilot-first experimentation (v2.7) | Full experiments at n=1 per cell can't detect realistic effect sizes. Pilot at n=3 on one fixture surfaces ceiling/variance issues cheaply |

## 12. Failure modes & escalation

| Failure | Detection | Response |
|---------|-----------|----------|
| Implementer ESCALATES | `STATUS: ESCALATE` in sub-agent reply | Escalation Protocol — categorize (SPEC_BLOCKER, ENV_BLOCKER, AMBIGUITY, TASK_BLOCKER), increment `escalation_count` (cap 3/task), respond per protocol |
| Combined Reviewer FAIL — implementer fault | `SPEC_FAULT: implementer_omitted` | Standard retry. Increment `review_retries` (cap 3). Re-dispatch with `## Fix Required\n{issues}` |
| Combined Reviewer FAIL — spec fault | `SPEC_FAULT: spec_contradicts` or `unclear` | Spec-edit branch (§9). Doesn't count against `review_retries` |
| Verifier FAIL — test broken | Verifier JSON says regression | Re-dispatch Implementer with `## Fix Required\n{failed tests}`. Increment `verifier_retries` (cap 3) |
| Verifier ENV_BLOCKER | Verifier JSON says environment unstable | ESCALATE — user must fix env (DB down, port conflict, etc.) |
| Debug artifact in commit | `PostToolUse` hook fires | Hook returns exit 2. Implementer sees rejection, auto-retries the edit |
| Malformed sub-agent output | `SubagentStop` hook detects missing fields | Hook returns exit 2. Orchestrator treats as Reviewer FAIL, re-dispatches |
| Sub-agent edits protected file | Agent Cleanup grep | Reset task, re-dispatch with explicit prohibition in prompt |
| State.json corrupted | Phase 0 resume read | Halt with "state file corrupted, manual inspection recommended" |
| Worktree dirty at start | Phase 0 clean check | Halt — "git status not empty, resolve before invoking" |

---

## 13. Update protocol

**Update this file whenever** you change any of:

| Topic in this doc | Triggering changes to update §X |
|-------------------|----------------------------------|
| Sub-agent catalog (§4) | New role added, role removed, model mapping changes |
| State.json schema (§5) | Any new field, any field semantics change |
| Isolation mechanisms (§6) | New hook, new worktree pattern, new safety boundary |
| Risk tiers (§7) | Criteria changes, upgrade rules change, mode-based overrides added |
| Quality scoring (§8) | Threshold changes, tier changes, trend rule changes |
| Eval harness (§10) | New fixture type, new measurement layer, new calibration tool |
| Failure modes (§12) | New ESCALATE category, new retry rule |

**Do not update this file for**:
- New fixture added (that's `evals/`)
- Bug fix to existing behavior (that's a commit message)
- Prose-only tweaks to SKILL.md (that's SKILL.md)

**On version bump** (SKILL.md frontmatter `metadata.version`): add a row
to `HISTORY.md` §1 referencing the relevant ARCHITECTURE.md sections that
changed in that version. Do not duplicate content — link to commits and
to experiment records.

**On new experiment**: if the experiment lands behavior changes, update
the corresponding ARCHITECTURE.md sections in the same commit that
merges the experiment to main. The experiment's own `docs/experiments/<name>/`
directory remains the detailed record; ARCHITECTURE.md remains the
synthesized current-state view.
