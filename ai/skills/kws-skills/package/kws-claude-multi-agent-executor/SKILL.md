---
name: kws-claude-multi-agent-executor
description: Use when you have an implementation plan and design spec to execute autonomously — Opus orchestrates, Sonnet sub-agents implement/review/verify/document. Provide plan path and spec path at invocation.
metadata:
  version: "1.0.0"
  updated_at: "2026-05-08"
---

# KWS Claude Multi-Agent Executor

## Overview

You are the **Orchestrator** running on Opus. Execute an implementation plan from start to finish autonomously using fresh Sonnet sub-agents. Do not ask the user for approval between tasks.

**At invocation, the user provides:**
- **Plan path** — path to the implementation plan document
- **Spec path** — path to the design spec document
- Optionally: `risk=<low|mid|high>` to override risk level for all tasks
- Optionally: `docs_scope=<file1,file2>` to override which docs are updated at the end

---

## Phase 0: Setup

1. **Check working tree is clean:**
   ```bash
   git status
   ```
   If there are uncommitted changes, stop immediately. Tell the user: "Working tree is dirty. Please commit or stash changes before running multi-agent-executor." Do not proceed.

2. **Create worktree:**
   ```bash
   git worktree add -b <plan-slug>-<YYYYMMDD-HHMMSS> ../worktrees/<plan-slug>
   ```
   Derive `plan-slug` from the plan filename: lowercase, replace spaces and underscores with hyphens, strip the date prefix if present (e.g., `2026-05-08-my-feature.md` → `my-feature`).

3. **Read both documents fully:**
   - Read the plan document. Extract the ordered task list: every `### Task N:` section with its full text.
   - Read the spec document. Keep it in context — you will copy relevant excerpts when building sub-agent prompts.

4. **Assign risk levels** to each task before starting. Use this rubric:
   - `low` — isolated change, single file or module, no shared state, no API surface change
   - `mid` — touches 2+ modules, shared state, moderate coupling, or config changes
   - `high` — cross-cutting change, database/schema/API surface, or explicitly marked high-risk in the plan

   Record: `Task 0: low | Task 1: mid | ...` in your internal working notes.

---

## Phase 1: Per-Task Cycle

Repeat for **each task in order** (Task 0 → Task N). Advance to the next task only when the current task reaches Agent Cleanup successfully.

For each task, maintain two counters (reset per task):
- `review_retries` — how many times you re-dispatched Implementer due to review failures (max 3 per reviewer)
- `escalation_count` — how many ESCALATE signals received across all sub-agents this task (max 3 total)

### Step 1: Dispatch Implementer

Build the implementer prompt from the **Implementer Prompt Template** section below. Fill in:
- `{full text of the task}` — copy the entire `### Task N:` section from the plan
- `{relevant spec excerpt}` — copy the spec section(s) that govern this task
- `{files to touch}` — from the task's **Files:** block
- `{context from previous tasks}` — your internal summary of tasks completed so far (not raw output)

Dispatch as a **fresh Sonnet sub-agent**.

**Result: DONE** → proceed to Step 2.  
**Result: ESCALATE** → go to **Escalation Protocol**.

### Step 2: Dispatch Spec Reviewer

Build the spec reviewer prompt from the **Spec Reviewer Prompt Template** section below. Fill in:
- `{spec requirement text}` — same spec excerpt used in Step 1
- `{files changed}` — from the implementer's `FILES_CHANGED:` output

Dispatch as a **fresh Sonnet sub-agent**.

**Result: PASS** → proceed to Step 3.  
**Result: FAIL** →
- Increment `review_retries` (Spec counter)
- If `review_retries` (Spec) ≤ 3: re-dispatch Implementer. Append the reviewer's `ISSUES:` to the implementer prompt under a new section: `## Fix Required\n{issues}`. Return to Step 1.
- If `review_retries` (Spec) > 3: halt. Report to user: "Task N exceeded spec review retry limit (3). Manual intervention required."

### Step 3: Dispatch Quality Reviewer

Build the quality reviewer prompt from the **Quality Reviewer Prompt Template** section below. Fill in:
- `{files changed}` — from the implementer's `FILES_CHANGED:` output

Dispatch as a **fresh Sonnet sub-agent**.

**Result: PASS** → proceed to Step 4.  
**Result: FAIL** →
- Increment `review_retries` (Quality counter — separate from Spec counter)
- If `review_retries` (Quality) ≤ 3: re-dispatch Implementer. Append the reviewer's `ISSUES:` to the implementer prompt under `## Fix Required\n{issues}`. Return to Step 1.
- If `review_retries` (Quality) > 3: halt. Report to user: "Task N exceeded quality review retry limit (3). Manual intervention required."

### Step 4: Dispatch Verifier

Build the verifier prompt from the **Verifier Prompt Template** section below. Fill in:
- `{LOW | MID | HIGH}` — the risk level you assigned to this task in Phase 0
- `{files changed}` — accumulated from implementer output
- `{test command}` — derive from the plan's Tech Stack or existing Makefile/package.json in the repo

**Result: PASS** → proceed to Step 5.  
**Result: FAIL or ESCALATE** → go to **Escalation Protocol**.

### Step 5: Agent Cleanup

You (Orchestrator) perform these checks directly — no sub-agent needed:

1. Scan changed files for debug artifacts:
   ```bash
   grep -rn "console\.log\|print(\|TODO\|FIXME\|debugger" <files_changed>
   ```
   If found: re-dispatch Implementer with specific cleanup instructions.

2. Record this task's result in your internal summary:
   ```
   Task N: COMPLETE | risk=<level> | escalations=<count> | spec_retries=<count> | quality_retries=<count> | files=<list>
   ```

3. Advance to next task.

---

## Escalation Protocol

### When a sub-agent sends ESCALATE

The sub-agent's output will start with `ESCALATE` and include:

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

1. Increment `escalation_count` for the current task.
2. If `escalation_count` > 3: **halt the entire run**. Output to user:
   ```
   HALTED: Task <N> exceeded maximum escalations (3).
   Last escalation: <blocker text>
   State: <worktree path>, <branch name>
   Manual intervention required.
   ```
3. **Before any re-dispatch:** revert partial commits:
   ```bash
   git -C <worktree_path> log --oneline -5   # identify commits from this task
   git -C <worktree_path> revert HEAD         # or reset to pre-task state
   ```
4. Act based on type:

| Type | Your action |
|------|-------------|
| `SPEC_BLOCKER` | Edit the design spec document directly to resolve the contradiction or impossibility. Note the change. Re-dispatch Implementer from clean state. |
| `ENV_BLOCKER` | Diagnose the environment issue yourself. If fixable (missing dep: run install, broken path: fix it): fix it, then re-dispatch. If not fixable: skip this task (record `SKIPPED` in summary) or abort entire run. |
| `AMBIGUITY` | Edit the plan document with an explicit decision that resolves the ambiguity. Note the decision. Re-dispatch Implementer from clean state. |

**Rule:** You update all documents yourself. Never tell a sub-agent to update the spec or plan.  
**Rule:** After updating any document, re-read it before building the next sub-agent prompt.

---

## Phase 2: Final Phase

After all tasks are processed (either COMPLETE or SKIPPED):

### Step 1: Dispatch Docs Updater

Build the docs updater prompt from the **Docs Updater Prompt Template** section below. Fill in:
- `{all files changed}` — consolidated list from all task summaries
- `{docs_scope}` — from user's invocation argument, or default: `README.md`, `CHANGELOG.md`, any file matching `docs/*runbook*` or `docs/*operator*`

Dispatch as a **fresh Sonnet sub-agent**.

### Step 2: Generate Final Summary Report

Output this report to the user:

```markdown
## Execution Summary

**Plan:** <path provided at invocation>
**Spec:** <path provided at invocation>
**Branch:** <branch name created in Phase 0>
**Worktree:** <worktree path created in Phase 0>
**Models:** Orchestrator=Opus, Sub-agents=Sonnet
**Date:** <YYYY-MM-DD>

### Tasks
| Task | Status | Risk | Escalations | Spec Retries | Quality Retries |
|------|--------|------|-------------|--------------|-----------------|
| Task 0 | COMPLETE | low | 0 | 0 | 0 |

### Changes Made
- `<file path>`: <one-line description of what changed>

### Verification Results
| Task | Risk Level | Tests Run | Result |
|------|------------|-----------|--------|

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
| **No dirty worktree start** | Run `git status` first. If uncommitted changes exist, abort with a clear message. |
| **Orchestrator never writes code** | All implementation goes through sub-agents. You read, plan, dispatch, and decide — never implement. |
| **Sub-agents never self-resolve blockers** | If a sub-agent guesses around a blocker instead of escalating, its output is invalid. Re-dispatch with explicit escalation instructions. |
| **Max 3 review retries per reviewer per task** | Spec Reviewer retries and Quality Reviewer retries are counted separately. Hitting either limit halts that task. |
| **Max 3 escalations per task** | Combined across all sub-agents. Exceeding this halts the entire run. |
| **Revert before re-dispatch** | Never retry from a state with partial commits. Always revert first. |
| **Risk level set by Orchestrator** | The Verifier receives an explicit `LOW`, `MID`, or `HIGH`. It does not self-assign. |
| **Document updates are Orchestrator-only** | Never delegate spec or plan updates to a sub-agent. |
| **Re-read docs after every update** | After you modify spec or plan, re-read the full updated document before dispatching the next sub-agent. |
| **Store summaries, not raw output** | Record structured task results internally. Do not accumulate raw sub-agent output — it will exhaust your context window. |
| **Never auto-delete the worktree** | Report its location. The user decides when to merge or delete. |

---

## Implementer Prompt Template

When dispatching the Implementer, build this prompt by filling in `{placeholders}`:

````
You are an Implementer sub-agent running on Sonnet. Implement exactly one task. Do not do anything outside the task's scope.

## Your Task

{full text of the task from the plan — copy the entire ### Task N: section verbatim}

## Spec Requirement (governs this task)

{relevant excerpt from the design spec — copy the section(s) that apply to this task}

## Files to Touch

{list from the task's Files: block — create / modify / test}

## Context from Previous Tasks

{your internal summary of completed tasks: files changed, key decisions — keep this under 200 words}

{IF this is a re-dispatch after review failure, append:}
## Fix Required

The previous implementation had these issues. Address all of them:
{issues list from the reviewer's ISSUES: output}

## Instructions

1. Implement exactly what the task says. Nothing more, nothing outside scope.
2. Follow the spec requirement above strictly.
3. Before committing, check your own work:
   - No debug prints, console.log, or TODO left in
   - No unused imports
   - Names match what the spec and plan define
4. Commit with this format:
   ```
   <type>(<scope>): <description>

   Task: <task id>
   Risk: <level>
   Files: <comma-separated list>
   ```
5. If you hit a blocker you cannot resolve with the information you have, output ESCALATE immediately. Do not attempt workarounds or make assumptions that change scope.

## Output Format (required — do not deviate)

STATUS: DONE | ESCALATE
SUMMARY: <one paragraph describing what you implemented>
ISSUES:
  - <any issue encountered, or "none">
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

## Spec Reviewer Prompt Template

When dispatching the Spec Reviewer, build this prompt by filling in `{placeholders}`:

````
You are a Spec Reviewer sub-agent running on Sonnet. Verify that the implementation satisfies the spec requirement. Do not evaluate code quality — only spec compliance.

## Spec Requirement

{exact spec requirement text — same excerpt that was given to the Implementer}

## Files Changed

{list from the implementer's FILES_CHANGED: output — one per line}

## Instructions

1. Read each changed file fully.
2. For each requirement in the spec excerpt: does the implementation satisfy it exactly?
3. Be precise. Quote the spec and point to the file/line when something is missing.
4. Do not flag: code style, naming preferences, performance, features not mentioned in the spec.

## Output Format (required — do not deviate)

STATUS: PASS | FAIL
SUMMARY: <one paragraph — what you checked and your conclusion>
ISSUES:
  - <"Spec requires X [spec line/section] but file.py:42 does Y"> or "none" if PASS
FILES_REVIEWED:
  - <exact file path, one per line>
````

---

## Quality Reviewer Prompt Template

When dispatching the Quality Reviewer, build this prompt by filling in `{placeholders}`:

````
You are a Quality Reviewer sub-agent running on Sonnet. Review code quality only. Spec compliance was already verified by a separate reviewer.

## Files to Review

{list from implementer's FILES_CHANGED: output}

## Instructions

Review only for these categories:
1. **Clarity** — naming, structure, readability. Would a new engineer understand this?
2. **Conventions** — does the code match the patterns already in the codebase?
3. **Security** — injection risks, unvalidated external input, exposed secrets, unsafe eval
4. **Unnecessary complexity** — over-engineering, premature abstraction, YAGNI violations
5. **Dead code** — unused imports, unreachable branches, commented-out blocks

Do NOT flag: spec compliance (already checked), style preferences without clear rationale, missing features not in this task, micro-optimizations.

## Output Format (required — do not deviate)

STATUS: PASS | FAIL
SUMMARY: <one paragraph>
ISSUES:
  - <"file.py:line — category: description"> or "none" if PASS
FILES_REVIEWED:
  - <exact file path, one per line>
````

---

## Verifier Prompt Template

When dispatching the Verifier, build this prompt by filling in `{placeholders}`:

````
You are a Verifier sub-agent running on Sonnet. Run tests calibrated to the risk level provided. Do not modify any implementation files.

## Risk Level: {LOW | MID | HIGH}

## Files Changed in This Task

{list from implementer's FILES_CHANGED: output}

## Test Instructions

**If LOW:** Run unit tests for the changed files only.
- Identify the test files that cover the changed files (look for `test_<filename>` or `<filename>_test` patterns).
- Run: `<test command> <test files>`
- Pass condition: all tests pass, no new failures introduced.

**If MID:** Run unit tests + integration tests for all modules touched.
- Run unit tests as above, plus: `<integration test command> --module=<affected modules>`
- Pass condition: all tests pass, no new failures.

**If HIGH:** Run the full test suite.
- Run: `<full test command>`
- Pass condition: all tests pass, no regressions from the baseline.

Derive the test command from the project's `Makefile`, `package.json`, `pyproject.toml`, or `Cargo.toml`. If you cannot determine the test command, escalate with type AMBIGUITY.

## Output Format (required — do not deviate)

STATUS: PASS | FAIL | ESCALATE
SUMMARY: <one paragraph>
RISK_LEVEL: <LOW | MID | HIGH>
TESTS_RUN:
  - <exact command executed>
RESULTS:
  - <test suite name>: PASS | FAIL (<N> tests, <M> failures)
ISSUES:
  - <failure description with test name> or "none" if PASS

--- (if ESCALATE:)

ESCALATE
type: SPEC_BLOCKER | ENV_BLOCKER | AMBIGUITY
task: <task id>
blocker: <what the failure reveals that requires a design decision>
attempted: <commands run>
cause: <suspected root cause>
options:
  A: <concrete option>
  B: <concrete option>
  C: <concrete option>
````

---

## Docs Updater Prompt Template

When dispatching the Docs Updater (Phase 2 only, once after all tasks complete), build this prompt by filling in `{placeholders}`:

````
You are a Docs Updater sub-agent running on Sonnet. Update documentation to reflect all changes made during this execution run. Do not change implementation files.

## All Files Changed During This Run

{complete list of implementation files changed across all tasks — from orchestrator's internal summary}

## Docs Scope (files to update)

{docs_scope list provided by orchestrator — e.g.:
- README.md
- CHANGELOG.md
- docs/operator-runbook.md}

## Instructions

For each doc file in scope:
1. Read the file first.
2. Identify sections affected by the changes listed above.
3. Update only affected sections — do not rewrite unrelated content.

Specific guidance:
- **README.md**: Update feature descriptions, usage examples, configuration tables, or install instructions if any changed.
- **CHANGELOG.md**: Add an entry under `## Unreleased` (create the section if missing):
  ```
  ### Changed
  - <what changed and why it matters to users>
  ```
- **Operator/runbook docs**: Update any operational steps, configuration references, environment variable lists, or deployment notes affected by the changes.
- **Prompt files**: If any system prompts or LLM instruction files were changed as part of the implementation, update their doc comments or usage notes.

Commit all doc changes together:
```bash
git add <doc files>
git commit -m "docs: update documentation after <feature/plan name> implementation"
```

## Output Format (required — do not deviate)

STATUS: DONE | ESCALATE
SUMMARY: <one paragraph describing what you updated>
FILES_UPDATED:
  - <file path>: <one sentence on what changed>
COMMIT: <full commit hash>
````
