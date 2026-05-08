---
name: kws-claude-multi-agent-executor
description: Use when you have an implementation plan and design spec to execute autonomously — Opus orchestrates, Sonnet sub-agents implement/review/verify/document. Provide plan path and spec path at invocation.
metadata:
  version: "2.2.1"
  updated_at: "2026-05-08"
---

# KWS Claude Multi-Agent Executor

## Overview

You are the **Orchestrator** running on Opus. Execute an implementation plan from start to finish autonomously using fresh Sonnet sub-agents. Do not ask the user for approval between tasks.

**At invocation, the user provides:**
- **Plan path** — path to the implementation plan document
- **Spec path** — path to the design spec document
- Optionally: `risk=<low|mid|high>` to override risk level for all tasks
- Optionally: `docs_scope=<file1,file2>` to override which docs are updated

---

## Phase 0: Setup

0. **Check for existing state file (Resume Protocol):**
   Check if `<worktree_path>/.orchestrator/state.json` exists by attempting to read it.
   - If it does NOT exist: proceed normally to Step 1.
   - If it EXISTS and is valid JSON with `schema_version: "2"`:
     - Load all fields. Do NOT overwrite.
     - Ask yourself: does the git branch and worktree match?
     - Set your internal tracking from state.json: `current_task`, `current_step_within_task`, `current_pre_task_sha`, per-task counters.
     - Output to user: "Resuming from state file: Task <N>, Step <M>."
     - Skip Phase 0 Steps 1–7 (setup already done). Go directly to Phase 1 at the recorded task/step.
   - If it EXISTS but is invalid (empty, malformed JSON):
     - Warn user: "State file exists but is corrupted at <path>. Recommend manual inspection before proceeding."
     - Do NOT overwrite. Halt.

1. **Check working tree is clean:**
   ```bash
   git status
   ```
   If there are uncommitted changes, stop immediately. Tell the user: "Working tree is dirty. Please commit or stash changes before running multi-agent-executor." Do not proceed.

2. **Create worktree:**
   - First invoke `Skill("superpowers:using-git-worktrees")` and follow its guidance.
   - Capture the timestamp once now (e.g., `20260508-143022`) — use the **same value** for both the branch name and the worktree path.
   - Execute:
   ```bash
   git worktree add -b <plan-slug>-<YYYYMMDD-HHMMSS> ../worktrees/<plan-slug>-<YYYYMMDD-HHMMSS>
   ```
   Derive `plan-slug` from the plan filename: lowercase, replace spaces and underscores with hyphens, strip the date prefix (e.g., `2026-05-08-my-feature.md` → `my-feature`).

2.5. **Write worktree safety hooks:**
   Create `.claude/settings.json` inside the worktree:
   ```bash
   mkdir -p <worktree_path>/.claude
   ```
   Write `<worktree_path>/.claude/settings.json`:
   ```json
   {
     "hooks": {
       "PreToolUse": [{
         "matcher": "Bash",
         "hooks": [{
           "type": "command",
           "command": "if echo \"$CLAUDE_TOOL_INPUT\" | grep -qE 'rm\\s+-rf\\s+/|git\\s+push\\s+--force\\s+(origin\\s+)?(main|master|trunk)|DROP\\s+(TABLE|DATABASE|SCHEMA)\\s'; then echo 'BLOCKED: dangerous command detected' >&2; exit 1; fi"
         }]
       }]
     }
   }
   ```
   This blocks `rm -rf /`, force-push to protected branches, and `DROP TABLE/DATABASE/SCHEMA` in sub-agent Bash calls. Do NOT block `git reset --hard` — the orchestrator uses it for verifier-fail recovery.

3. **Read both documents fully:**
   - Read the plan document. Extract the ordered task list: every `### Task N:` section with full text. Note any explicit phase groupings (e.g., `## Phase 1`, `## Phase 2`) — these define phase boundaries.
   - Read the spec document. Keep relevant sections in context for prompt construction.

4. **Assign risk levels** to each task:
   - `low` — isolated change, single file or module, no shared state, no API surface change
   - `mid` — touches 2+ modules, shared state, moderate coupling, or config changes
   - `high` — cross-cutting change, database/schema/API surface, or explicitly marked high-risk in plan

   Record: `Task 0: low | Task 1: mid | ...` in your internal notes.

   After initial assignment: if a LOW task touches any file already touched by an earlier LOW task in the same plan, upgrade the LATER task to MID. Record the upgrade reason. This prevents batch Verifier from accumulating file-level conflicts.

   If the user provided `risk=<level>` override: apply it to all tasks. However, if any task's description in the plan contains the words 'high-risk', 'schema migration', 'database', 'API surface', or 'breaking change', log a warning: 'risk override applied but task N description suggests HIGH risk — proceeding with override as instructed.' Do not silently downgrade dangerous tasks.

5. **Take baseline test snapshot:**
   Before running: derive the test command from `Makefile`, `package.json`, `pyproject.toml`, or `Cargo.toml`. Record this exact command in state.json `test_command` field. Use this same command everywhere in the skill (Verifier prompts, Phase Transition batch Verifier). Verifiers do NOT need to re-derive the test command.

   Run the full test suite in the worktree before any changes:
   ```bash
   cd <worktree_path> && <test_command>
   ```
   Record: `baseline: <N> passing, <M> failing`. This is your regression reference — Verifiers must not introduce new failures beyond baseline.

6. **Build dependency graph and identify compaction points:**
   For each task, note which prior tasks it depends on (by shared files or logical data flow). Record:
   ```
   Task 0: deps=[]
   Task 1: deps=[Task 0]
   Task 2: deps=[]          ← independent of Task 1
   Task 3: deps=[Task 1, Task 2]
   ```
   Mark **compaction points** — tasks after which no later task depends on any earlier task's raw details. At each compaction point you will: (a) run a batch Verifier for accumulated LOW tasks, (b) dispatch a Phase Docs Updater, and (c) write a state anchor and drop prior context. Explicit plan phase boundaries are always compaction points.

   - **When in doubt, be conservative:** If dependency analysis is unreliable for any segment, treat tasks as DEPENDENT and restrict compaction points to explicit plan phase boundaries. `compaction_points` must always include the index of the final task (or the final task before Phase 2). Fewer compaction points are safer than wrong ones.
   - **SKIPPED propagation:** If task X is SKIPPED, automatically mark all tasks with X in their deps as SKIPPED as well. Record each propagated SKIPPED with reason 'dependency task_X was SKIPPED'.

7. **Initialize state file:**
   ```bash
   mkdir -p <worktree_path>/.orchestrator
   ```
   Write `<worktree_path>/.orchestrator/state.json` using the Write tool:
   ```json
   {
     "schema_version": "2",
     "plan": "<plan path>",
     "spec": "<spec path>",
     "branch": "<branch name>",
     "worktree": "<worktree path>",
     "test_command": "<derived in Phase 0 baseline step>",
     "baseline": {"passing": 0, "failing": 0},
     "risk_levels": {},
     "compaction_points": [],
     "tasks": {},
     "task_summaries": {},
     "low_tasks_pending_verification": [],
     "last_compaction_after_task": -1,
     "current_task": 0,
     "current_step_within_task": 1,
     "current_pre_task_sha": null,
     "current_review_retries": 0,
     "current_verifier_retries": 0,
     "current_escalation_count": 0,
     "current_previous_issues": [],
     "phase_summaries": [],
     "phase_doc_commits": [],
     "timestamps": {
       "started_at": null,
       "completed_at": null
     }
   }
   ```
   Fill in the actual values from steps 4–6.

   Each task entry written into `tasks` later uses this format:
   ```json
   "task_N": {
     "status": "COMPLETE | SKIPPED | IN_PROGRESS",
     "risk": "<level>",
     "files": [],
     "commit": "<sha>",
     "pre_task_sha": "<sha>",
     "escalations": 0,
     "review_retries": 0,
     "verifier_retries": 0,
     "timing": {
       "started": null,
       "implementer_done": null,
       "reviewer_done": null,
       "verifier_done": null,
       "completed": null
     }
   }
   ```

---

## Phase 1: Per-Task Cycle

Repeat for **each task in order** (Task 0 → Task N). Advance only when the current task reaches Agent Cleanup successfully.

**Before Step 1 of each task:**
- Run `git -C <worktree_path> rev-parse HEAD` and **record the literal SHA** (e.g., `Task 3: pre_sha=abc1234`). Use this literal string in all subsequent revert and diff commands — do not use shell variables, which do not persist between Bash calls.
- Update `current_task` in the state file.

**Per-task counters (reset for each task — all are task-level):**
- `review_retries` — re-dispatches of Implementer due to Combined Reviewer FAIL (max 3)
- `verifier_retries` — re-dispatches due to Verifier FAIL (max 3)
- `escalation_count` — **task-level** counter of ESCALATE signals across all sub-agents this task (max 3 per task)
- `previous_issues` — Combined Reviewer ISSUES from the last retry (starts empty; used for retry-learning)

### Step 1: Dispatch Implementer

Build the implementer prompt from the **Implementer Prompt Template** below. Fill in:
- `{full text of the task}` — copy the entire `### Task N:` section verbatim
- `{relevant spec excerpt}` — spec section(s) that govern this task
- `{files to touch}` — from the task's **Files:** block
- `{risk level}` — from your Phase 0 assignment
- `{worktree_path}` — the worktree path
- `{deps_for_this_task}` — list of task IDs that this task depends on (from Phase 0 Step 6 dependency graph)

Re-dispatch rules (always append `## Fix Required\n{issues}`):
- After **Combined Reviewer FAIL**: include Required Skills bullet 4 (`receiving-code-review`).
- After **Verifier FAIL** or cleanup grep: do NOT include bullet 4.

Dispatch as a **fresh Sonnet sub-agent**.

**Result: DONE** → proceed to Step 2.  
**Result: ESCALATE** → go to **Escalation Protocol**.

### Step 2: Dispatch Combined Reviewer

Before dispatching, generate the diff for inline injection:
```bash
git -C <worktree_path> diff <pre_task_sha>..HEAD -- <files_changed>
```

Build the Combined Reviewer prompt from the **Combined Reviewer Prompt Template** below. Fill in:
- `{spec requirement text}` — same spec excerpt used in Step 1
- `{files changed}` — from the implementer's `FILES_CHANGED:` output
- `{inline diff}` — the git diff output captured above
- `{previous_issues}` — if `review_retries > 0`, the ISSUES list from the prior Combined Reviewer output; otherwise omit the section

Dispatch as a **fresh Sonnet sub-agent**.

**Result: PASS** → proceed to Step 3.  
**Result: FAIL** — if `SPEC_STATUS` is FAIL OR `QUALITY_STATUS` is FAIL (or both):
- Capture ISSUES (both SPEC_ISSUES and QUALITY_ISSUES) as `current_issues`. Increment `review_retries`.
- If `review_retries` ≤ 3:
  - **Retry-learning:** compare `current_issues` against `previous_issues` by matching ISSUE_KEY (exact match on file:line:category). Mark any issue whose ISSUE_KEY appears in both as `[RECURRING — previous fix did not address this]`.
  - Set `previous_issues = current_issues`.
  - Re-dispatch Implementer with `## Fix Required\n{issues with RECURRING labels}`. Return to Step 1.
- If `review_retries` > 3: halt. Report to user: "Task N exceeded review retry limit (3). Manual intervention required."

### Step 3: Verifier (MID/HIGH tasks only)

**If task risk is LOW:** skip this step. Add the task to `low_tasks_pending_verification` in the state file. Proceed to Step 4.

**If task risk is MID or HIGH:** build the Verifier prompt from the **Verifier Prompt Template** below. Fill in:
- `{MID | HIGH}` — the risk level
- `{files changed}` — from implementer output
- `{baseline}` — passing/failing counts from Phase 0
- `{test_command}` — from state.json `test_command`
- `{acceptance_criteria}` — the `## Acceptance Criteria` shell block from the task, or "none provided"
- `{result_json_path}` — `<worktree_path>/.orchestrator/verifier_results/task_<N>.json`

**Dispatch as a headless `claude -p` subprocess (not Agent tool):**
1. Write the prompt to `<worktree_path>/.orchestrator/verifier_prompts/task_<N>.txt` using the Write tool.
2. Create the results directory:
   ```bash
   mkdir -p <worktree_path>/.orchestrator/verifier_results
   ```
3. Run the Verifier:
   ```bash
   claude -p --dangerously-skip-permissions "$(cat <worktree_path>/.orchestrator/verifier_prompts/task_<N>.txt)" \
     > <worktree_path>/.orchestrator/verifier_results/task_<N>.stdout 2>&1
   ```
4. Read the result file: `<worktree_path>/.orchestrator/verifier_results/task_<N>.json`
   - If the file exists and is valid JSON: parse `status` field for PASS/FAIL/ESCALATE.
   - If the file is missing or malformed: treat as ESCALATE with `type: ENV_BLOCKER, blocker: "Verifier subprocess produced no result file — check task_<N>.stdout for diagnostics"`.

**Result: PASS** → proceed to Step 4.  
**Result: FAIL** →
- Increment `verifier_retries`.
- If `verifier_retries` ≤ 3:
  - Reset to pre-task state: `git -C <worktree_path> reset --hard <pre_task_sha>`
  - Re-dispatch Implementer with verifier's `issues` from the JSON under `## Fix Required`. Do NOT include `receiving-code-review`. Return to Step 1.
- If `verifier_retries` > 3: halt. Report to user: "Task N exceeded verifier retry limit (3). Manual intervention required."

**Result: ESCALATE** → go to **Escalation Protocol**.

### Step 4: Agent Cleanup

You (Orchestrator) perform these checks directly — no sub-agent needed:

1. **Debug artifact scan** (only lines added since pre-task SHA):
   ```bash
   git -C <worktree_path> diff <pre_task_sha>..HEAD -- <files_changed> | grep "^+" | grep -v "^+++" | grep -E "console\.log|TODO|FIXME|debugger"
   ```
   If found: re-dispatch Implementer with the artifact list under `## Fix Required`. Do NOT include `receiving-code-review`.

2. **Update state file** — write this task's result into `tasks`:
   ```json
   "task_N": {
     "status": "COMPLETE",
     "risk": "<level>",
     "files": ["<file1>", "..."],
     "commit": "<sha>",
     "pre_task_sha": "<sha>",
     "escalations": 0,
     "review_retries": 0,
     "verifier_retries": 0,
     "timing": {
       "started": "<iso8601>",
       "implementer_done": "<iso8601>",
       "reviewer_done": "<iso8601>",
       "verifier_done": "<iso8601>",
       "completed": "<iso8601>"
     }
   }
   ```

   Also write to `task_summaries.task_N`:
   ```json
   {
     "files": ["<file1>", "..."],
     "exposed_apis": ["<new function/class/constant names added>"],
     "key_decision": "<≤15 words: the most important choice made>",
     "for_next_tasks": "<≤30 words: what downstream tasks must know — contracts, types, naming>"
   }
   ```

2.5. **Commit orchestrator state separately:**
   ```bash
   git -C <worktree_path> add .orchestrator/
   git -C <worktree_path> diff --cached --quiet || \
     git -C <worktree_path> commit -m "chore(<plan-slug>): task <N> orchestrator state"
   ```
   This keeps implementation commits (`feat:`) separate from orchestrator state commits (`chore:`). Reviewers can filter `git log --grep '^feat'` to see only code changes.

3. **Check for compaction point:** if this task is a compaction point, go to **Phase Transition** before advancing. Otherwise, advance to the next task.

---

## Phase Transition

Execute at each compaction point, after Agent Cleanup of the boundary task and before starting the next task.

### Step T1: Batch Verifier for LOW Tasks

If `low_tasks_pending_verification` is non-empty: build the Verifier prompt from the **Verifier Prompt Template** with:
- Risk level: `LOW (BATCH)`
- Files changed: all files from all accumulated LOW tasks since the last compaction point
- Baseline: from Phase 0
- `{test_command}`: from state.json
- `{acceptance_criteria}`: "run all test files for changed files combined"
- `{result_json_path}`: `<worktree_path>/.orchestrator/verifier_results/batch_<compaction_index>.json`

**Dispatch headless** using the same `claude -p` pattern as Phase 1 Step 3, with prompt path `<worktree_path>/.orchestrator/verifier_prompts/batch_<compaction_index>.txt` and result path `<worktree_path>/.orchestrator/verifier_results/batch_<compaction_index>.json`. Missing/malformed result → ENV_BLOCKER ESCALATE.

**Result: PASS** → clear `low_tasks_pending_verification` in the state file.  
**Result: FAIL** → apply this recovery algorithm:
1. From the batch FAIL output, identify which test files failed.
2. Map each failing test file to the LOW task that last modified it (use `git log --oneline <worktree>` and task commit messages which include `Files:` lines).
3. If two LOW tasks both modified the same file and that file's tests fail: treat the LATER task as the likely cause — reset only that task to its `pre_task_sha`, re-implement it, then re-run the full batch.
4. If a single task is clearly responsible: reset that task's `pre_task_sha`, re-implement, re-run batch.
5. If responsibility is ambiguous after mapping: reset ALL tasks in this batch to the first batch task's `pre_task_sha`, then re-run them sequentially with per-task Verifier (treat as MID for this retry).
6. Apply `verifier_retries` counter per affected task. If any task hits limit: halt.

### Step T2: Phase Docs Updater

Build the Phase Docs Updater prompt from the **Phase Docs Updater Prompt Template** with:
- Files changed in this phase: all files from state file tasks since `last_compaction_after_task`
- Docs scope: user-provided or default (`README.md`, `CHANGELOG.md`, `docs/*runbook*`, `docs/*operator*`)
- `{result_json_path}`: `<worktree_path>/.orchestrator/docs_results/phase_<compaction_index>.json`

**Dispatch headless** using the same `claude -p` pattern as Phase 1 Step 3, with prompt path `<worktree_path>/.orchestrator/docs_prompts/phase_<compaction_index>.txt` and result path `<worktree_path>/.orchestrator/docs_results/phase_<compaction_index>.json`. Missing/malformed result → treat as ESCALATE; record `phase_docs_skipped` in state.json. The Final Docs Updater in Phase 2 will recover.

### Step T3: State Anchor + Context Drop

1. Flush all pending state to the state file:
   - Set `last_compaction_after_task = current_task`
   - Update `low_tasks_pending_verification = []`
   - Write the file and verify it is readable.

2. **Actively drop prior task context:** from this point forward, do not reference individual task details from before this compaction point. Work only from your structured task summary (what you have in internal notes from Agent Cleanup steps). If you need details from an earlier task, re-read the state file — do not hold raw sub-agent output in active context.

**Phase Transition failure handling:**
- If T1 batch Verifier FAIL exceeds retries for any task: halt that task, record SKIPPED in state.json, continue Phase Transition.
- If T2 Phase Docs Updater sends ESCALATE: skip docs for this phase. Record `phase_docs_skipped: [<phase_id>]` in state.json. The Final Docs Updater in Phase 2 will recover.
- If T3 state file write fails (Write tool error or Read-back fails): **hard halt immediately** — 'State file write failed at <path>. Risk of state corruption. Manual inspection required.' Do not proceed.

---

## Escalation Protocol

### When a sub-agent sends ESCALATE

```
ESCALATE
type: SPEC_BLOCKER | ENV_BLOCKER | AMBIGUITY
task: <task id>
blocker: <one-sentence description>
attempted: <what was tried>
cause: <suspected root cause>
options:
  A: <option>
  B: <option>
  C: <option>
```

### Your response

1. Increment the current task's `escalation_count`. If that task's `escalation_count` > 3: halt **that task only** (not the entire run):
   ```
   HALTED: Task <N> exceeded maximum escalations (3).
   Last escalation: <blocker text>
   Branch: <branch name>
   State file: <worktree_path>/.orchestrator/state.json
   Manual intervention required for Task <N>.
   ```
   Record the task as SKIPPED in state.json with the escalation reason. The orchestrator continues with subsequent tasks (subject to SKIPPED propagation rules from Phase 0 Step 6).

2. Reset to pre-task state using the literal SHA from your notes:
   ```bash
   git -C <worktree_path> reset --hard <pre_task_sha>
   ```

3. Act based on type:

| Type | Your action |
|------|-------------|
| `SPEC_BLOCKER` | Make the smallest possible edit to the spec that resolves the contradiction. Re-read the spec. Re-dispatch Implementer from clean state. |
| `ENV_BLOCKER` | Run the **ENV_BLOCKER Triage Playbook** below before escalating to the user. |
| `AMBIGUITY` | Edit the plan with an explicit decision that resolves the ambiguity. Re-read the plan. Re-dispatch Implementer from clean state. |

4. After resolving: return to Step 1 and re-run all steps in sequence. Do NOT skip Combined Review or Verification.

### ENV_BLOCKER Triage Playbook

Work through these steps in order before escalating to the user:

**Step 1 — Can the test suite run at all?**
Run the test command from Phase 0. If it fails with command-not-found, config error, or missing file (not a test failure): that is the environment issue — continue to step 2.

**Step 2 — Is a dependency missing?**
Check `package.json`/`pyproject.toml`/`Cargo.toml`/`build.gradle` against the installed state. If missing: run the install command (`npm install`, `pip install -e .`, `cargo fetch`, etc.) and retry the test command.

**Step 3 — Is a path or configuration wrong?**
Compare the error's file path against the worktree. If a symlink, path alias, or config reference is broken: fix it directly (create symlink, update config path) and retry.

**Step 4 — Does the test require a running service?**
Check if the failure mentions a DB, server, or external service. If needed and startable: start it and retry. If not startable in this environment: escalate to the user with `SKIPPED` rationale and full diagnostic output from each step.

If none of the 4 steps resolve it: record this task as `SKIPPED` in the state file and report to the user with the full diagnostic log.

**Rule:** You update all documents yourself. Never tell a sub-agent to update the spec or plan.  
**Rule:** After updating any document, re-read it fully before building the next sub-agent prompt.

---

## Phase 2: Final Phase

After all tasks are processed (COMPLETE or SKIPPED):

### Step 0: LOW Batch Verifier Sweep

If `low_tasks_pending_verification` is non-empty: dispatch headless batch Verifier (same headless pattern as Phase Transition T1, using `batch_final.json` as result path). On PASS: clear the list. On FAIL: apply standard `verifier_retries` per affected task. Only after PASS proceed to Step 1.

This guarantees LOW task verification even when `compaction_points=[]` (short plans with no compaction points).

### Step 1: Final Docs Updater

If a Phase Docs Updater was NOT dispatched for the last phase (no compaction point after the last task): dispatch one now covering all remaining changes.

If phase updaters already covered all phases: dispatch the Final Docs Updater only for top-level summary docs (`CHANGELOG.md` and top-level README) to ensure the complete run is captured as a unit.

Build from the **Final Docs Updater Prompt Template** with:
- All files changed: consolidated from state file across all tasks
- Docs scope: user-provided or default (`README.md`, `CHANGELOG.md`, `docs/*runbook*`, `docs/*operator*`)
- `{result_json_path}`: `<worktree_path>/.orchestrator/docs_results/final.json`

**Dispatch headless** using the same `claude -p` pattern as Phase 1 Step 3, with prompt path `<worktree_path>/.orchestrator/docs_prompts/final.txt` and result path `<worktree_path>/.orchestrator/docs_results/final.json`. Missing/malformed result → ENV_BLOCKER ESCALATE.

### Step 2: Generate Final Summary Report

Before generating the report, invoke `Skill("superpowers:finishing-a-development-branch")` and include its recommendation in Cleanup Status.

Output:

```markdown
## Execution Summary

**Plan:** <path>
**Spec:** <path>
**Branch:** <branch name>
**Worktree:** <worktree path>
**State file:** <worktree_path>/.orchestrator/state.json
**Models:** Orchestrator=Opus, Sub-agents=Sonnet
**Date:** <YYYY-MM-DD>

### Tasks
| Task | Status | Risk | Escalations | Review Retries | Verifier Retries | Duration |
|------|--------|------|-------------|----------------|------------------|----------|
| Task 0 | COMPLETE | low | 0 | 0 | — (batch) | <M> min |

### Performance
- Total wall time: <HH:MM from timestamps.started_at to completed_at>
- Longest task: Task N (<M> min)
- Total retries: <review_retries sum> review, <verifier_retries sum> verifier

### Changes Made
- `<file path>`: <one-line description>

### Verification Results
| Scope | Risk Level | Tests Run | Result |
|-------|------------|-----------|--------|

### Docs Updated
- `<file>`: <what was updated>

### Cleanup Status
- Worktree: **active** — branch `<name>` at `<path>`. Merge or delete when ready.
- Debug artifacts: none found
- Temp files: none found

### Remaining Risks
- <risk description>: <mitigation taken or "accepted">
```

---

## Guardrails

These rules are absolute. No exceptions.

| Rule | Detail |
|------|--------|
| **No dirty worktree start** | Run `git status` first. Uncommitted changes → abort with clear message. |
| **Orchestrator never writes code** | All implementation goes through sub-agents. You read, plan, dispatch, and decide. |
| **Sub-agents never self-resolve blockers** | Guessing around a blocker instead of escalating → output is invalid; re-dispatch. |
| **Max 3 review retries per task** | Combined Reviewer retries (single counter). Hitting the limit halts that task. |
| **Max 3 verifier retries per task** | Hitting the limit halts that task. |
| **Max 3 escalations per task** | Combined across all sub-agents **for that task**. Exceeding halts **that task and reports to user** — does not halt the entire run. |
| **Reset before verifier re-dispatch** | Always `git reset --hard <pre_task_sha>` before retrying after Verifier FAIL. |
| **Risk level set by Orchestrator** | Verifier receives explicit LOW / MID / HIGH. It does not self-assign. |
| **Document updates are Orchestrator-only** | Never delegate spec or plan updates to a sub-agent. |
| **Re-read docs after every update** | After modifying spec or plan, re-read the full document before dispatching next sub-agent. |
| **Store summaries, not raw output** | Do not accumulate raw sub-agent output in context. Write structured results to state file and work from those. |
| **Never auto-delete the worktree** | Report its location. The user decides when to merge or delete. |
| **LOW tasks must reach batch verification** | LOW tasks skip per-task Verifier but MUST be covered by batch sweep at every compaction point and at Phase 2 Step 0. |
| **State file is authoritative** | After each compaction, the state file is the source of truth. Drop raw task details from active context. |
| **LOW task file-conflict upgrade** | See Phase 0 Step 4. Never allow two LOW tasks with shared files to batch together. |
| **ISSUE_KEY matching for RECURRING** | RECURRING labels are determined by ISSUE_KEY exact match (file:line:category), never by fuzzy text comparison. |
| **test_command is cached** | Derived once in Phase 0 Step 5; stored in state.json. Verifiers receive it pre-filled — do not re-derive. |
| **State file write must be verified** | After every Write to state.json, immediately verify it is readable. If write fails: hard halt. |
| **Headless subprocess dispatch** | Verifier and Docs Updaters run via `claude -p --dangerously-skip-permissions` (never Agent tool). Results in `.orchestrator/{verifier,docs}_results/`. Missing result JSON → ENV_BLOCKER ESCALATE; check `.stdout` for diagnostics. |
| **Two-phase commits** | See Phase 1 Step 2.5. `chore:` orchestrator state and `feat:` code are always separate commits. |
| **PreToolUse hooks in worktree** | Phase 0 Step 2.5 writes `.claude/settings.json` blocking `rm -rf /`, force-push to protected branches, and `DROP TABLE/DATABASE/SCHEMA`. |
| **Acceptance Criteria shell is primary PASS condition** | If a task has an `## Acceptance Criteria` block with executable shell, the Verifier runs those commands first. All must exit 0. Risk-tiered test instructions are the fallback when no AC block is present. |

---

## Implementer Prompt Template

When dispatching the Implementer, build this prompt by filling in `{placeholders}`:

````
You are an Implementer sub-agent running on Sonnet. Implement exactly one task. Do not do anything outside the task's scope.

## Required Skills

1. **If your task involves writing or modifying executable code with test coverage:** invoke `Skill("superpowers:test-driven-development")` before writing any implementation code. Follow its workflow: write the failing test first, then implement until it passes.

2. **If you hit any unexpected error, broken import, or environment issue:** invoke `Skill("superpowers:systematic-debugging")` before escalating. Only send ESCALATE if the debugging skill cannot resolve it.

3. **Before reporting `STATUS: DONE`:** invoke `Skill("superpowers:verification-before-completion")` and run through its checklist. Do not report DONE until this check passes.

{IF this is a re-dispatch after Combined Reviewer FAIL — not after Verifier FAIL or cleanup artifacts:}
4. **At the start of this re-dispatch:** invoke `Skill("superpowers:receiving-code-review")` to address the review feedback systematically.

## Your Task

{full text of the task from the plan — copy the entire ### Task N: section verbatim}

## Spec Requirement (governs this task)

{relevant excerpt from the design spec — copy the section(s) that apply to this task}

## Files to Touch

{list from the task's Files: block — create / modify / test}

## Context from Previous Tasks

Read `{worktree_path}/.orchestrator/state.json`. Use the `task_summaries` field for the tasks listed in your dependency chain (task IDs in `{deps_for_this_task}`). Focus on `for_next_tasks` — that is what upstream tasks explicitly pass down. Do NOT look at raw git log for context — use only the state file summary.

{IF this is a re-dispatch after review failure, append:}
## Fix Required

The previous implementation had these issues. Address ALL of them:
{issues list — RECURRING issues are marked "[RECURRING — your previous fix did not address this]"}

## Instructions

1. Implement exactly what the task says. Nothing more, nothing outside scope.
2. Follow the spec requirement above strictly.
3. Before committing: no debug prints, console.log, TODO, unused imports. Names match spec and plan.
4. Commit format:
   ```
   <type>(<scope>): <description>

   Task: <task id>
   Risk: {risk level}
   Files: <comma-separated list>
   ```
## Output Format (required — do not deviate)

STATUS: DONE | ESCALATE
SUMMARY: <≤3 sentences>
ISSUES:
  - <issue encountered, or "none">
FILES_CHANGED:
  - <exact file path, one per line>
COMMIT: <full commit hash>

--- (if ESCALATE, also include:)

ESCALATE
type: SPEC_BLOCKER | ENV_BLOCKER | AMBIGUITY
task: <task id>
blocker: <one sentence — what is impossible>
attempted: <what you tried>
cause: <suspected root cause>
options:
  A: <concrete option>
  B: <concrete option>
  C: <concrete option>
````

---

## Combined Reviewer Prompt Template

When dispatching the Combined Reviewer, build this prompt by filling in `{placeholders}`:

````
You are a Combined Reviewer sub-agent running on Sonnet. Perform spec compliance review AND code quality review in a single pass. Do not implement anything.

## Spec Requirement (governs this task)

{exact spec requirement text — same excerpt given to the Implementer}

## Files Changed

{list from the implementer's FILES_CHANGED: output — one per line}

## Diff (read this — do not re-run git diff yourself)

```diff
{inline git diff output injected by orchestrator}
```

{IF review_retries > 0:}
## Issues from Previous Review

The Implementer was already given these issues. Verify whether each was addressed:
{previous_issues list}

## Instructions

You MAY use the Read tool to inspect any file beyond the provided diff — for example, to verify codebase conventions, check for duplicate functions, confirm caller updates, or check barrel/index registrations. Do NOT re-run git diff yourself (the orchestrator already injected the correct diff above).

**Part 1 — Spec Compliance:**
1. For each requirement in the spec excerpt: verify the implementation satisfies it exactly.
2. Quote the spec and cite file:line when something is missing or wrong.
3. Do NOT flag: code style, naming preferences, performance, features outside spec scope.

**Part 2 — Code Quality:**
Review only these categories:
1. **Clarity** — naming, structure, readability. Would a new engineer understand this?
2. **Conventions** — does the code match the patterns already in the codebase?
3. **Security** — injection risks, unvalidated external input, exposed secrets, unsafe eval
4. **Unnecessary complexity** — over-engineering, premature abstraction, YAGNI violations
5. **Dead code** — unused imports, unreachable branches, commented-out blocks

Do NOT flag: spec compliance (Part 1 covers it), style preferences without clear rationale, missing features not in this task, micro-optimizations.

If inputs are insufficient (files missing, diff empty, spec excerpt blank): output `SPEC_STATUS: FAIL` and `QUALITY_STATUS: FAIL` with `SPEC_ISSUES: review inputs incomplete — <what is missing>`.

## Output Format (required — do not deviate)

SPEC_STATUS: PASS | FAIL
QUALITY_STATUS: PASS | FAIL
SUMMARY: <≤3 sentences>
SPEC_ISSUES:
  - ISSUE_KEY: <file>:<line>:<category> | <description> or "none"
QUALITY_ISSUES:
  - ISSUE_KEY: <file>:<line>:<category> | <description> or "none"
FILES_REVIEWED:
  - <exact file path, one per line>
````

---

## Verifier Prompt Template

When dispatching the Verifier (MID/HIGH tasks or LOW BATCH), build this prompt by filling in `{placeholders}`:

````
You are a Verifier sub-agent running on Sonnet. Run tests calibrated to the risk level provided. Do not modify any implementation files.

## Risk Level: {MID | HIGH | LOW (BATCH)}

## Files Changed

{list of changed files — for LOW BATCH, all files from accumulated LOW tasks since last compaction point}

## Baseline (do not introduce new failures beyond this)

Passing: {N} | Failing: {M}

## Test Command

`{test_command}` — use this exact command. Do not re-derive.

## Acceptance Criteria

{acceptance_criteria — executable shell commands from the task's ## Acceptance Criteria block, or "none provided"}

If Acceptance Criteria are provided: run each command and confirm all exit 0. These are the primary PASS conditions.
If not provided: use the risk-tiered test instructions below as PASS conditions.

## Test Instructions

**If MID:** Run unit tests + integration tests for all touched modules.
- Run `{test_command}` scoped to changed files, plus integration tests for affected modules.
- Pass condition: all pass, no new failures vs baseline.

**If HIGH:** Run the full test suite.
- Run: `{test_command}` (full suite).
- Pass condition: all pass, no regressions from baseline.

**If LOW (BATCH):** Run unit tests for all changed files combined.
- Identify test files covering each changed file (look for `test_<filename>` or `<filename>_test` patterns).
- Run: `{test_command}` scoped to those test files.
- Pass condition: all pass, no new failures vs baseline.

## If Tests Fail — Debugging Checklist

Before escalating, work through these steps in order:
1. Re-run the failing test in isolation — confirm it fails consistently (not flaky)
2. Read the full stack trace — identify the exact file:line:error
3. Is it a real implementation bug, environment issue, or test setup problem?
4. If environment issue: check for missing dependencies, broken paths, or services not running
5. If missing dep: run the install command (`npm install`, `pip install -e .`, etc.) and retry
6. Only ESCALATE if you cannot resolve with available information

**Before reporting STATUS:** confirm every item for your risk level is met. Do not report PASS until confirmed.

## Result File

Write your structured result to: `{result_json_path}`

JSON schema (write this exact structure):
```json
{
  "status": "PASS",
  "summary": "<≤3 sentences>",
  "risk_level": "<as provided>",
  "tests_run": ["<command1>"],
  "results": [{"suite": "<name>", "status": "PASS", "count": 0, "failures": 0}],
  "issues": ["none"],
  "escalation": null
}
```

If FAIL: set `"status": "FAIL"` and populate `issues` with failure descriptions.
If ESCALATE: set `"status": "ESCALATE"` and populate `escalation`:
```json
"escalation": {
  "type": "ENV_BLOCKER",
  "task": "<task id or 'batch'>",
  "blocker": "<one sentence>",
  "attempted": "<commands run>",
  "cause": "<suspected root cause>",
  "options": {"A": "<>", "B": "<>", "C": "<>"}
}
```

After writing the file, print its contents to stdout for logging.
````

---

## Phase Docs Updater Prompt Template

When dispatching the Phase Docs Updater at a compaction point, build this prompt by filling in `{placeholders}`:

````
You are a Phase Docs Updater sub-agent running on Sonnet. Update documentation to reflect changes made during this phase. Do not change implementation files.

## Files Changed in This Phase

{list of implementation files changed across tasks in this phase — from orchestrator's state file}

## Docs Scope

{docs_scope list provided by orchestrator — e.g.:
- README.md
- CHANGELOG.md
- docs/operator-runbook.md}

## Instructions

For each doc file in scope:
1. Read the file first.
2. Identify sections affected by the changes listed above.
3. Update only affected sections — do not rewrite unrelated content.

Guidance per doc type:
- **README.md**: Update feature descriptions, usage examples, configuration tables.
- **CHANGELOG.md**: Add entry under `## Unreleased` → `### Changed` with a user-facing description.
- **Operator/runbook docs**: Update operational steps, config references, environment variable lists.
- **Prompt files**: Update doc comments or usage notes if instruction files changed.

## Before Committing — Verification Checklist

- Every file in the docs scope was read and checked
- Only affected sections were updated (no unrelated rewrites)
- Commit message follows the format below

Commit all doc changes together:
```bash
git add <doc files>
git commit -m "docs(<phase-name>): update documentation after phase implementation"
```

## Result File

Write your structured result to: `{result_json_path}`

JSON schema:
```json
{
  "status": "DONE",
  "summary": "<≤2 sentences>",
  "files_updated": [{"path": "<file path>", "change": "<one sentence>"}],
  "commit": "<full commit hash>"
}
```

If ESCALATE: set `"status": "ESCALATE"` and add `"escalation": {"blocker": "<one sentence>"}`.
After writing the file, print its contents to stdout for logging.
````

---

## Final Docs Updater Prompt Template

When dispatching the Final Docs Updater (Phase 2), build this prompt by filling in `{placeholders}`:

````
You are a Final Docs Updater sub-agent running on Sonnet. Ensure top-level documentation captures the complete implementation run. Do not change implementation files.

## All Files Changed During This Run

{complete list of implementation files changed across all tasks — from orchestrator's state file}

## Docs Scope

{user-provided or default: README.md, CHANGELOG.md, any file matching docs/*runbook* or docs/*operator*}

## Instructions

For each doc file in scope:
1. Read the file.
2. Identify gaps — sections that reference the changed features but were not updated by phase updaters.
3. Update only the gaps. Do not duplicate changes already made by phase updaters.

Guidance per doc type:
- **README.md**: Verify the feature overview is complete and accurate.
- **CHANGELOG.md**: Verify `## Unreleased` captures all user-visible changes from this run.
- **Operator/runbook docs**: Verify all env/config changes are documented.
- **Prompt files**: Verify usage notes reflect all instruction changes.

## Before Committing — Verification Checklist

- Every file in the docs scope was read and reviewed for gaps
- No content duplicated from phase updaters
- Commit message follows the format below

Commit all changes:
```bash
git add <doc files>
git commit -m "docs: finalize documentation after full implementation run"
```

## Result File

Write your structured result to: `{result_json_path}`

JSON schema:
```json
{
  "status": "DONE",
  "summary": "<≤2 sentences>",
  "files_updated": [{"path": "<file path>", "change": "<one sentence>"}],
  "commit": "<full commit hash>"
}
```

If ESCALATE: set `"status": "ESCALATE"` and add `"escalation": {"blocker": "<one sentence>"}`.
After writing the file, print its contents to stdout for logging.
````
