# KWS Codex Plan Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development only when the user explicitly asks for subagents, delegation, parallel work, or `subagents=on`. Otherwise implement this plan in the current Codex session task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `kws-codex-plan-executor` as the single forward-looking skill for executing implementation plans in Codex, while preserving the old prompt-generator behavior through `mode=prompt` and a temporary deprecated wrapper.

**Architecture:** The new skill is a Codex-native executor with three modes: `interactive` for current-session execution, `headless` for `codex exec` automation, and `prompt` for legacy fresh-session/handoff prompt export. Runtime behavior lives in `SKILL.md` and concise reference templates; deterministic parsing, state validation, and eval checks live in scripts. The previous `kws-new-session-plan-prompt-gpt-5-5` skill becomes a compatibility shim that points users to `kws-codex-plan-executor mode=prompt`.

**Tech Stack:** Codex skills, Markdown prompt templates, Python 3 scripts, Bash eval runner, `codex exec --json --output-last-message --output-schema`, git worktrees, JSON state files, existing `kws-skills` manifest/sync tooling.

---

## Scope And Non-Goals

This plan creates a new executor skill and migrates future usage to it. It does not delete the old prompt-generator skill in the first release.

In scope:

- New package skill: `ai/skills/kws-skills/package/kws-codex-plan-executor/`.
- Interactive execution mode that can run a plan directly in the current Codex session.
- Headless execution mode based on `codex exec`, disabled unless explicitly requested.
- Prompt export mode that replaces normal use of `kws-new-session-plan-prompt-gpt-5-5`.
- State file schema, task parsing, risk ledger, verification ladder, retry budget, final summary.
- Eval harness for prompt mode and basic execution mode.
- Package metadata, README, changelog, and sync validation.

Out of scope for the first release:

- Detached self-spawn as a default behavior.
- Unconditional multi-agent execution.
- `--dangerously-bypass-approvals-and-sandbox` in normal usage.
- Automatic push, PR creation, merge, deploy, or release.
- Deleting the deprecated prompt-generator skill from manifest.

## File Structure

Create:

- `ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md` - trigger, mode selection, execution workflow, stop rules.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/ARCHITECTURE.md` - current-state design.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/HISTORY.md` - version timeline and migration notes.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/agents/openai.yaml` - UI metadata.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/templates/fresh-session-prompt.txt` - legacy prompt export body, moved from the old skill and adjusted to the new name.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/templates/spark-scout-bullets.ko.txt` - opt-in Spark scout section, moved from the old skill.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/state-schema.md` - authoritative `.codex-orchestrator/state.json` schema.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/mode-contracts.md` - `interactive`, `headless`, and `prompt` mode details.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/execution-cycle.md` - per-task cycle, review, verification, retry, cleanup.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/headless-runner.md` - `codex exec` invocation, JSON capture, schema output.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/preflight-reviewer-prompt.md` - mechanical plan/spec audit prompt.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/verifier-prompt.md` - verification prompt for headless verifier runs.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/prompt-export-checklist.md` - migrated pre-send checklist.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/change-protocol.md` - edit/release protocol.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/parse_plan.py` - deterministic task extraction and Files block validation.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/validate_state.py` - state schema validator.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/run.sh` - Codex eval runner.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_prompt.py` - deterministic prompt-output checker.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_execution.py` - deterministic state/diff/test checker.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/judge.md` - LLM judge for subjective quality only.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/fixtures/01-prompt-only.yaml`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/fixtures/02-no-spark.yaml`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/fixtures/03-continuation.yaml`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/fixtures/04-interactive-docs-only.yaml`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/fixtures/05-missing-files-block.yaml`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/baselines/.gitkeep`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/docs/experiments/README.md`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/docs/experiments/_template/README.md`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/docs/experiments/_template/JOURNAL.md`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/docs/experiments/_template/decisions/D000-template.md`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/docs/experiments/_template/findings/F000-template.md`

Modify:

- `ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/SKILL.md` - reduce to deprecated wrapper after the new prompt mode passes evals.
- `ai/skills/kws-skills/manifest.json` - add `kws-codex-plan-executor`, update package version and skill versions.
- `ai/skills/kws-skills/README.md` - add the new skill and deprecation note.
- `ai/skills/kws-skills/CHANGELOG.md` - add the release entry.

Do not modify in the first release:

- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md`

## Design Decisions

- The new executor is the forward path. The old prompt generator remains only as a temporary compatibility entrypoint.
- Default mode is `interactive`, not `headless`.
- `headless` mode uses `codex exec`, but never defaults to `--dangerously-bypass-approvals-and-sandbox`.
- Subagents are optional. The executor may spawn Codex subagents only when the user explicitly asks for subagents, delegation, parallel work, or passes `subagents=on`.
- Prompt export is a mode of the executor, not a separate long-term skill.
- Deterministic scripts own mechanical parsing and eval checks. Prompt prose owns judgment.
- Eval correctness comes from scripts first. LLM-as-judge is limited to subjective quality and regression notes.

## State Schema Summary

The executor writes `.codex-orchestrator/state.json` in the active worktree.

Required top-level fields:

```json
{
  "schema_version": "1",
  "mode": "interactive",
  "workspace": "/abs/path",
  "plan": "/abs/path/plan.md",
  "spec": "/abs/path/spec.md",
  "branch": "codex/example",
  "worktree": "/abs/path/worktree",
  "test_command": "pytest",
  "baseline": {"status": "unknown", "summary": ""},
  "current_task": "task_0",
  "current_phase": "preflight",
  "risk_levels": {},
  "tasks": {},
  "review_issue_keys": {},
  "verification": {},
  "session_owned_resources": [],
  "last_checkpoint": null,
  "timestamps": {
    "started_at": null,
    "updated_at": null,
    "completed_at": null
  }
}
```

Per-task fields:

```json
{
  "status": "pending",
  "title": "Task title",
  "risk": "low",
  "risk_reason": "single docs file",
  "files_declared": [],
  "files_changed": [],
  "pre_task_sha": null,
  "commit": null,
  "review_retries": 0,
  "verifier_retries": 0,
  "issue_keys": [],
  "verification": [],
  "summary": "",
  "started_at": null,
  "completed_at": null
}
```

## Task 0: Baseline Audit

**Files:**
- Read: `ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/SKILL.md`
- Read: `ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/templates/fresh-session-prompt.txt`
- Read: `ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/references/pre-send-checklist.md`
- Read: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md`
- Read: `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/run.sh`
- Read: `ai/skills/kws-skills/tests/test-sync.sh`

- [x] **Step 1: Confirm clean working state**

Run:

```bash
git status --short
```

Expected: no unrelated dirty files, or unrelated files documented before editing.

- [x] **Step 2: Confirm Codex CLI headless capabilities**

Run:

```bash
codex exec --help | sed -n '1,180p'
```

Expected: output includes `--json`, `--output-last-message`, `--output-schema`, `--sandbox`, and `--cd`.

- [x] **Step 3: Record migrated prompt invariants**

Open the old prompt-generator skill and list invariants that must survive in `mode=prompt`:

```text
- verified absolute paths
- prompt-only output
- gpt-5.5 high routing ownership
- conservative Spark evidence packing
- no-Spark removal
- source-of-truth plan git-status handling
- continuation ledger handling
- session-owned cleanup boundaries
- risk-scaled verification
```

- [x] **Step 4: Record executor-only invariants**

Open the Claude executor and record patterns to adapt:

```text
- state file is authoritative
- plan/spec preflight before execution
- risk levels and retry budgets
- deterministic eval harness
- experiment and history records
- raw output files for verification failures
```

Do not copy:

```text
- default detached self-spawn
- default dangerous permission bypass
- Claude-specific hook semantics
- unconditional multi-agent execution
```

## Task 1: Scaffold New Skill

**Files:**
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/agents/openai.yaml`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/ARCHITECTURE.md`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/HISTORY.md`

- [x] **Step 1: Create directories**

Run:

```bash
mkdir -p ai/skills/kws-skills/package/kws-codex-plan-executor/{agents,templates,references,scripts,evals/fixtures,evals/baselines,docs/experiments/_template/decisions,docs/experiments/_template/findings}
```

- [x] **Step 2: Write initial `SKILL.md` frontmatter**

Create `ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md` with this frontmatter:

```markdown
---
name: kws-codex-plan-executor
description: Use when executing an implementation plan in Codex from a plan path and optional spec/design docs, or when exporting a fresh-session/handoff prompt from the same plan.
metadata:
  version: "1.0.0"
  updated_at: "2026-05-13"
---
```

- [x] **Step 3: Add concise `SKILL.md` body**

The body must stay under 500 lines and directly link references instead of embedding all details. Required sections:

```markdown
# KWS Codex Plan Executor

## Overview

Execute implementation plans in Codex or export a paste-ready prompt from the same inputs.

Default behavior is interactive execution in the current Codex session. Headless execution and prompt export require explicit mode selection.

## Invocation

Supported arguments:

- `plan=<abs-or-repo-relative-path>` required except resume-only flows.
- `spec=<path>` optional.
- `docs=<path1,path2>` optional.
- `workspace=<path>` optional.
- `mode=interactive|headless|prompt|handoff` optional, default `interactive`.
- `subagents=on|off` optional, default `off` unless the user explicitly asked for subagents, delegation, or parallel work.
- `headless_sandbox=workspace-write|read-only|danger-full-access` optional, default `workspace-write`.

## Hard Boundary

Do not use `--dangerously-bypass-approvals-and-sandbox` unless the user explicitly requests it and the target is an isolated throwaway repo or CI sandbox.

## Workflow

1. Resolve and verify paths.
2. Select mode.
3. For `prompt` or `handoff`, use `templates/fresh-session-prompt.txt` and `references/prompt-export-checklist.md`.
4. For `interactive`, follow `references/execution-cycle.md`.
5. For `headless`, follow `references/headless-runner.md`.
6. Maintain `.codex-orchestrator/state.json` using `references/state-schema.md`.
7. Validate using scripts before claiming completion.

## Stop Rules

- Missing or unreadable plan: ask one short question or report blocker.
- Dirty worktree with related ambiguity: stop and report.
- Missing `Files:` blocks in execution mode: stop before edits.
- Unclear acceptance criteria on mid/high risk tasks: stop for clarification unless the plan gives an honest substitute.
- Verification failure without root cause after 3 same-root retries: stop with checkpoint.

## Maintenance

Use `references/change-protocol.md` before editing this skill. Update `HISTORY.md`, `ARCHITECTURE.md`, package metadata, and eval baselines for behavior changes.
```

- [x] **Step 4: Write `agents/openai.yaml`**

Create:

```yaml
interface:
  display_name: "KWS Codex Plan Executor"
  short_description: "Execute implementation plans in Codex or export plan handoff prompts"
  default_prompt: "Use $kws-codex-plan-executor with plan=<path> and optional spec=<path> to execute the plan, or mode=prompt to export a fresh-session prompt."
```

- [x] **Step 5: Write `ARCHITECTURE.md`**

Include these sections:

```markdown
# Architecture - kws-codex-plan-executor

## Purpose
## Modes
## Runtime Flow
## State File Contract
## Subagent Policy
## Headless Codex Exec Contract
## Prompt Export Compatibility
## Eval Surface
## Migration From kws-new-session-plan-prompt-gpt-5-5
```

- [x] **Step 6: Write `HISTORY.md`**

Initial entry:

```markdown
# Skill History - kws-codex-plan-executor

## v1.0.0 - Initial Codex executor and prompt-export replacement (2026-05-13)

- Introduced a Codex-native plan executor with interactive, headless, prompt, and handoff modes.
- Migrated the fresh-session prompt generator contract into `mode=prompt`.
- Added deterministic parsing, state validation, and eval harness structure.
- Kept `kws-new-session-plan-prompt-gpt-5-5` as a temporary deprecated wrapper.
```

## Task 2: Add Deterministic Plan Parsing And State Validation

**Files:**
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/parse_plan.py`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/validate_state.py`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/state-schema.md`

- [x] **Step 1: Implement `parse_plan.py`**

Create a Python script with this CLI:

```bash
python3 scripts/parse_plan.py --plan /tmp/kws-executor-eval/repo/plan.md --repo-root /tmp/kws-executor-eval/repo --output /tmp/kws-executor-eval/tasks.json
```

Behavior:

- Parse `### Task N:` headings.
- Extract task title and full markdown body.
- Extract paths under `**Files:**`.
- Reject out-of-repo `..` paths.
- Return nonzero if no tasks exist.
- Return nonzero if any task has no `Files:` block in execution modes.

Output shape:

```json
{
  "plan": "/abs/path/plan.md",
  "tasks": [
    {
      "id": "task_0",
      "number": 0,
      "title": "Example",
      "body": "full markdown",
      "files": ["path/from/repo"],
      "has_acceptance_criteria": true
    }
  ]
}
```

- [x] **Step 2: Test `parse_plan.py` manually**

Run:

```bash
tmp="$(mktemp -d)"
cat > "$tmp/plan.md" <<'EOF'
### Task 0: Add note

**Files:**
- Create: docs/example.md

## Acceptance Criteria

```bash
test -f docs/example.md
```
EOF
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/parse_plan.py \
  --plan "$tmp/plan.md" \
  --repo-root "$tmp" \
  --output "$tmp/tasks.json"
jq '.tasks[0].id' "$tmp/tasks.json"
```

Expected: `"task_0"`.

- [x] **Step 3: Implement `validate_state.py`**

Create a Python script with this CLI:

```bash
python3 scripts/validate_state.py /tmp/kws-executor-eval/repo/.codex-orchestrator/state.json
```

Checks:

- JSON is parseable.
- `schema_version`, `mode`, `workspace`, `plan`, `branch`, `worktree`, `current_task`, `current_phase`, `tasks`, and `timestamps` exist.
- `mode` is one of `interactive`, `headless`, `prompt`, `handoff`.
- Every task has `status`, `risk`, `files_declared`, `review_retries`, and `verifier_retries`.

- [x] **Step 4: Write `state-schema.md`**

Document the schema summary from this implementation plan and include the validator command:

```bash
python3 scripts/validate_state.py .codex-orchestrator/state.json
```

## Task 3: Define Execution Mode Contracts

**Files:**
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/mode-contracts.md`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/execution-cycle.md`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/headless-runner.md`

- [x] **Step 1: Write `mode-contracts.md`**

Include this decision table:

```markdown
# Mode Contracts

| Mode | Trigger | Mutates repo | Uses codex exec | Default sandbox |
|------|---------|--------------|-----------------|-----------------|
| `interactive` | default | yes | no | current session policy |
| `headless` | `mode=headless` | yes | yes | `workspace-write` |
| `prompt` | `mode=prompt` | no | no | n/a |
| `handoff` | `mode=handoff` or continuation request | no | no | n/a |

`interactive` is the default because it preserves Codex app context, connector availability, user-visible progress, and approval handling.

`headless` is for eval, CI, or explicitly detached work. It must write logs and final output paths.

`prompt` and `handoff` produce only a fenced `text` prompt and must not edit the repo.
```

- [x] **Step 2: Write `execution-cycle.md`**

Required execution phases:

```markdown
# Execution Cycle

## Phase 0: Preflight
- Read repo-local instructions.
- Verify plan/spec/docs paths.
- Check git status and branch.
- Create or select `codex/...` worktree when appropriate.
- Parse plan with `scripts/parse_plan.py`.
- Assign task risk.
- Initialize `.codex-orchestrator/state.json`.

## Phase 1: Task Loop
- Confirm a 5-line `TASK EXECUTION CONTRACT`.
- Implement the task locally unless subagents are explicitly allowed.
- Review spec compliance and code quality on `gpt-5.5 high`.
- Run risk-scaled verification.
- Record raw output paths for failures.
- Update state and checkpoint.

## Phase 2: Finish
- Run final verification.
- Check docs impact.
- Validate state file.
- Summarize changed files, verification, branch/worktree, resources, and residual risk.
```

Subagent rule:

```markdown
Use `spawn_agent` only when the user explicitly asked for subagents, delegation, parallel work, or passed `subagents=on`. Otherwise execute locally.
```

- [x] **Step 3: Write `headless-runner.md`**

Include safe default command:

```bash
codex exec \
  --cd "$WORKTREE_ABS" \
  --sandbox workspace-write \
  --json \
  --output-last-message "$WORKTREE_ABS/.codex-orchestrator/headless-final.md" \
  "$PROMPT" \
  > "$WORKTREE_ABS/.codex-orchestrator/headless.jsonl" 2>&1
```

Include schema-output variant:

```bash
codex exec \
  --cd "$WORKTREE_ABS" \
  --sandbox workspace-write \
  --json \
  --output-schema "$WORKTREE_ABS/.codex-orchestrator/final.schema.json" \
  --output-last-message "$WORKTREE_ABS/.codex-orchestrator/headless-final.json" \
  "$PROMPT" \
  > "$WORKTREE_ABS/.codex-orchestrator/headless.jsonl" 2>&1
```

Hard rule:

```markdown
Do not use `--dangerously-bypass-approvals-and-sandbox` unless the user explicitly requested it and the run target is an isolated throwaway repository or CI sandbox.
```

## Task 4: Migrate Prompt Export Mode

**Files:**
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/templates/fresh-session-prompt.txt`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/templates/spark-scout-bullets.ko.txt`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/prompt-export-checklist.md`
- Read: `ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/templates/fresh-session-prompt.txt`
- Read: `ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/templates/spark-scout-bullets.ko.txt`
- Read: `ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/references/pre-send-checklist.md`

- [x] **Step 1: Copy prompt templates**

Run:

```bash
cp ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/templates/fresh-session-prompt.txt \
   ai/skills/kws-skills/package/kws-codex-plan-executor/templates/fresh-session-prompt.txt
cp ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/templates/spark-scout-bullets.ko.txt \
   ai/skills/kws-skills/package/kws-codex-plan-executor/templates/spark-scout-bullets.ko.txt
cp ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/references/pre-send-checklist.md \
   ai/skills/kws-skills/package/kws-codex-plan-executor/references/prompt-export-checklist.md
```

- [x] **Step 2: Edit copied template references**

In the copied `fresh-session-prompt.txt`, keep the existing prompt behavior but change references that imply a separate prompt-generator skill. The output prompt should say the fresh session is executing the plan, not invoking the old skill.

Required preserved strings:

```text
gpt-5.5 high
gpt-5.3-codex-spark
.codex-orchestrator/session.json
HANDOFF CHECKPOINT
ISSUE_KEY=
```

- [x] **Step 3: Update checklist name**

In `prompt-export-checklist.md`, replace the title with:

```markdown
# Prompt Export Checklist
```

Keep all old checks unless an eval proves they are obsolete.

## Task 5: Add Preflight Reviewer And Verifier Prompts

**Files:**
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/preflight-reviewer-prompt.md`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/verifier-prompt.md`

- [x] **Step 1: Write mechanical preflight reviewer prompt**

The prompt must audit plan/spec only. It must not suggest architecture or style improvements.

Required JSON schema:

```json
{
  "status": "PASS",
  "summary": "short summary",
  "issues": [
    {
      "severity": "BLOCKER",
      "task": "task_0",
      "category": "missing_files|missing_ac|contract_mismatch|dep_inconsistency|out_of_repo|ambiguity",
      "description": "one sentence",
      "evidence": "file:line or section",
      "suggested_fix": "smallest fix"
    }
  ]
}
```

- [x] **Step 2: Write verifier prompt**

The verifier prompt must accept:

```text
{risk_level}
{files_changed}
{baseline}
{test_command}
{acceptance_criteria}
{result_json_path}
```

Required result JSON:

```json
{
  "status": "PASS",
  "commands": [
    {"cmd": "pytest", "exit_code": 0, "raw_output": ".codex-orchestrator/raw/task_0-pytest.txt"}
  ],
  "issues": [],
  "notes": "short"
}
```

Failure JSON:

```json
{
  "status": "FAIL",
  "commands": [
    {"cmd": "pytest", "exit_code": 1, "raw_output": ".codex-orchestrator/raw/task_0-pytest.txt"}
  ],
  "issues": [
    {"issue_key": "tests/test_example.py:test_name:assertion", "summary": "one sentence"}
  ],
  "notes": "short"
}
```

## Task 6: Add Eval Harness

**Files:**
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/run.sh`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_prompt.py`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_execution.py`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/judge.md`
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/fixtures/*.yaml`

- [x] **Step 1: Implement `check_prompt.py`**

CLI:

```bash
python3 evals/check_prompt.py --fixture evals/fixtures/01-prompt-only.yaml --output /tmp/final.md
```

Checks:

- Exactly one fenced `text` block when fixture requires prompt-only.
- No `{{...}}` tokens.
- Includes expected paths.
- Includes or excludes Spark strings according to fixture.
- Does not include implementation-started language in prompt export result.

Output:

```json
{
  "fixture": "01-prompt-only",
  "passed": true,
  "checks": {
    "one_text_block": true,
    "no_template_tokens": true,
    "model_routing": true
  },
  "failures": []
}
```

- [x] **Step 2: Implement `check_execution.py`**

CLI:

```bash
python3 evals/check_execution.py --fixture evals/fixtures/04-interactive-docs-only.yaml --workdir /tmp/repo
```

Checks:

- `.codex-orchestrator/state.json` exists and validates.
- Expected files changed.
- Expected test command passes.
- No out-of-scope file changed.
- Final state marks tasks complete or expected blocked.

- [x] **Step 3: Implement `evals/run.sh`**

The runner must:

1. Create a temp parent directory per fixture.
2. Initialize a git repo.
3. Write fixture plan/spec/docs.
4. Commit bootstrap.
5. Invoke:

```bash
codex exec \
  --cd "$tmpdir" \
  --sandbox workspace-write \
  --json \
  --output-last-message "$tmpdir/.harness/final.md" \
  "/kws-codex-plan-executor plan=plan.md spec=spec.md mode=$mode $fixture_args" \
  > "$tmpdir/.harness/run.jsonl" 2>&1 || true
```

6. Run `check_prompt.py` for prompt fixtures.
7. Run `check_execution.py` for execution fixtures.
8. Optionally run `judge.md` only after deterministic checks.
9. Write `evals/baselines/v<skill-version>.json`.

- [x] **Step 4: Add initial fixtures**

Fixture `01-prompt-only.yaml`:

```yaml
name: prompt-only
mode: prompt
user_request: "Generate prompt only for plan.md"
expected:
  prompt_only: true
  must_include:
    - "gpt-5.5 high"
    - ".codex-orchestrator/session.json"
  must_not_include:
    - "{{PLAN_PATH}}"
    - "{{OPTIONAL_DOCUMENT_BULLETS}}"
```

Fixture `04-interactive-docs-only.yaml`:

```yaml
name: interactive-docs-only
mode: interactive
plan: |
  ### Task 0: Add docs note

  **Files:**
  - Create: docs/example.md

  ## Acceptance Criteria

  ```bash
  test -f docs/example.md
  ```
spec: |
  Create docs/example.md with the exact text "hello executor".
expected:
  files_changed:
    - docs/example.md
  test_after: "test -f docs/example.md && grep -q 'hello executor' docs/example.md"
```

## Task 7: Deprecate Old Prompt Generator

**Files:**
- Modify: `ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/SKILL.md`
- Modify: `ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/HISTORY.md`
- Modify: `ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/ARCHITECTURE.md`

- [x] **Step 1: Change old skill description only after new prompt evals pass**

Update frontmatter:

```yaml
description: Use only for legacy references to the old fresh-session prompt generator; prefer kws-codex-plan-executor mode=prompt for new plan execution prompts.
metadata:
  version: "2.4.0"
  updated_at: "2026-05-13"
```

- [x] **Step 2: Replace old body with compatibility wrapper**

Keep a short body:

```markdown
# KWS New Session Plan Prompt

This skill is deprecated.

For new usage, invoke `kws-codex-plan-executor mode=prompt` with the same `plan=`, `spec=`, `docs=`, and `workspace=` paths.

If this legacy skill was explicitly invoked, generate the same prompt by following `kws-codex-plan-executor` prompt mode. Do not maintain separate prompt rules here.
```

- [x] **Step 3: Add history note**

Add:

```markdown
### v2.4.0 - Deprecated in favor of kws-codex-plan-executor (2026-05-13)

- Moved forward usage to `kws-codex-plan-executor mode=prompt`.
- Stopped maintaining a separate prompt-generation contract in this skill.
```

## Task 8: Update Package Metadata

**Files:**
- Modify: `ai/skills/kws-skills/manifest.json`
- Modify: `ai/skills/kws-skills/README.md`
- Modify: `ai/skills/kws-skills/CHANGELOG.md`

- [x] **Step 1: Update `manifest.json`**

Set package version to `2.6.0` and add:

```json
"kws-codex-plan-executor"
```

Add skill version:

```json
"kws-codex-plan-executor": {
  "version": "1.0.0",
  "updated_at": "2026-05-13"
}
```

Update old skill if deprecated:

```json
"kws-new-session-plan-prompt-gpt-5-5": {
  "version": "2.4.0",
  "updated_at": "2026-05-13"
}
```

- [x] **Step 2: Update `README.md`**

Add to included skills:

```markdown
- `kws-codex-plan-executor`
```

Add note:

```markdown
`kws-new-session-plan-prompt-gpt-5-5` is retained as a temporary legacy wrapper. New plan execution and prompt export should use `kws-codex-plan-executor`.
```

- [x] **Step 3: Update `CHANGELOG.md`**

Add:

```markdown
## 2.6.0 - 2026-05-13

- Added `kws-codex-plan-executor` as the forward Codex-native plan execution skill.
- Added interactive, headless, prompt, and handoff mode contracts.
- Migrated fresh-session prompt export into the new executor skill.
- Deprecated `kws-new-session-plan-prompt-gpt-5-5` as a compatibility wrapper.
- Added deterministic eval harness scaffolding for prompt and execution fixtures.
```

## Task 9: Validate

**Files:**
- Read: `ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md`
- Read: `ai/skills/kws-skills/manifest.json`
- Read: `ai/skills/kws-skills/tests/test-sync.sh`

- [x] **Step 1: Validate new skill metadata**

Run:

```bash
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  /Users/kws/source/private/Archive/ai/skills/kws-skills/package/kws-codex-plan-executor
```

Expected:

```text
Skill is valid!
```

- [x] **Step 2: Run package sync test**

Run:

```bash
ai/skills/kws-skills/tests/test-sync.sh
```

Expected: exits 0.

- [x] **Step 3: Run script smoke tests**

Run:

```bash
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/parse_plan.py --help
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/validate_state.py --help
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_prompt.py --help
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_execution.py --help
```

Expected: each command prints usage and exits 0.

- [x] **Step 4: Run eval smoke fixture**

Run:

```bash
cd ai/skills/kws-skills/package/kws-codex-plan-executor
./evals/run.sh evals/fixtures/01-prompt-only.yaml
```

Expected: deterministic prompt checks pass.

- [x] **Step 5: Run whitespace and diff checks**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; status shows only intended files.

- [x] **Step 6: Refresh graph only if code files changed**

Because this plan creates Python and Bash scripts, run:

```bash
graphify update .
```

Expected: graph update completes. If graphify is unavailable, record the failure and reason in the final summary.

## Task 10: Migration Close-Out

**Files:**
- Read: `ai/skills/kws-skills/package/kws-codex-plan-executor/HISTORY.md`
- Read: `ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5/HISTORY.md`
- Read: `ai/skills/kws-skills/CHANGELOG.md`

- [x] **Step 1: Confirm old/new skill roles**

Check:

```bash
rg -n "deprecated|mode=prompt|kws-codex-plan-executor" \
  ai/skills/kws-skills/package/kws-new-session-plan-prompt-gpt-5-5 \
  ai/skills/kws-skills/package/kws-codex-plan-executor \
  ai/skills/kws-skills/README.md \
  ai/skills/kws-skills/CHANGELOG.md
```

Expected: old skill clearly points to new skill; new skill owns execution and prompt export.

- [x] **Step 2: Commit**

Run:

```bash
git add ai/skills/kws-skills docs/superpowers/plans/2026-05-13-kws-codex-plan-executor.md graphify-out
git commit -m "feat(skills): add codex plan executor"
```

Expected: commit succeeds.

## Acceptance Criteria

- `kws-codex-plan-executor` exists as a valid skill.
- New skill supports `interactive`, `headless`, `prompt`, and `handoff` modes in docs and workflow.
- Default execution mode is interactive.
- Headless mode uses safe `codex exec` defaults.
- Dangerous bypass is never default.
- Subagent dispatch is gated on explicit user request or `subagents=on`.
- Old prompt-generator skill is deprecated but not deleted.
- Package manifest, README, and changelog are synchronized.
- Deterministic eval harness exists and at least the prompt-only fixture passes.
- `quick_validate.py`, `test-sync.sh`, `git diff --check`, and script smoke tests pass.
- `graphify update .` is run if script files are added or modified.

## Open Risks

- Codex CLI behavior may change. Mitigation: keep headless invocation isolated in `references/headless-runner.md` and eval runner.
- Subagent availability differs between Codex app and CLI. Mitigation: make subagents optional and explicitly gated.
- Prompt export could drift from old behavior during migration. Mitigation: copy old fixtures first and run deterministic prompt checks before deprecating old skill.
- Execution evals can become costly. Mitigation: keep initial fixtures small and deterministic; reserve LLM judge for subjective quality only.
