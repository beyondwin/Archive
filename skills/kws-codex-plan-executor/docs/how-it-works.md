# How It Works

This document explains the current `kws-codex-plan-executor` runtime. It is
maintenance documentation, not the prompt that Codex loads by default.

## Purpose

The skill takes a plan path and optional source documents, then either:

- executes the plan in Codex (`interactive` or `headless`)
- exports a prompt that another Codex session can execute (`prompt` or
  `handoff`)

The same invariants apply across both execution and prompt export. Prompt export
does not run or log anything, but the generated prompt must instruct the future
agent to follow the same state, verification, and logging contracts.

## Inputs

Supported runtime arguments are defined in [../SKILL.md](../SKILL.md):

- `plan=<path>`: required except resume-only flows
- `spec=<path>`: optional
- `docs=<path1,path2>`: optional
- `workspace=<path>`: optional
- `resume=latest|<state-path>|<run_id>`: optional
- `mode=interactive|headless|prompt|handoff`: default `interactive`
- `subagents=on|off`: default `off`
- `headless_sandbox=workspace-write|read-only`: default `workspace-write`

Paths may be absolute or repository-relative. Execution modes reject missing
plans, unreadable source files, missing task file blocks, and ambiguous resume
state before making edits.

## Plan Parsing

`scripts/parse_plan.py` extracts executable task metadata from visible Markdown.
It intentionally blanks hidden regions before parsing:

- fenced code blocks
- HTML comments
- indented code blocks

This prevents examples, commented-out plans, or pasted snippets from becoming
executable tasks. The parser preserves line positions but parses only normalized
visible text.

Execution modes require each task to have a visible file block. Accepted
headings include English aliases such as `Files`, `Affected files`, and
`Modified files`, plus Korean aliases such as `수정 파일`, `변경 파일`,
`대상 파일`, and `파일`.

Visible `Depends on:` lines are parsed as optional dependency metadata. They are
validated for known task ids and cycle freedom, but they do not bypass per-task
contracts or change task completion semantics.

## Execution Modes

### Interactive

`interactive` runs in the current Codex session. The executor:

1. reads repo-local instructions
2. verifies paths
3. checks git status
4. parses the plan
5. classifies dirty files as related or unrelated
6. initializes a `run_id`
7. builds `context.json`
8. initializes `context_health`
9. writes state under `.codex-orchestrator/runs/<run_id>/`
10. executes each task locally unless subagents were explicitly allowed
11. refreshes `context_health` at task and blocker boundaries
12. records verification, completion audit, and terminal lifecycle outcome

Interactive execution is described in
[../references/execution-cycle.md](../references/execution-cycle.md).

### Headless

`headless` is launched by a supervising Codex session through `codex exec`. The
target process must not launch another nested `codex exec`; it is already the
target executor.

Headless prompts must bootstrap applicable skills because parent-session skill
state is not assumed to carry over. Implementation work explicitly names
`using-superpowers` and `test-driven-development`.

Headless artifacts include:

- `.codex-orchestrator/runs/<run_id>/headless.jsonl`
- `.codex-orchestrator/runs/<run_id>/headless-final.md` or
  `headless-final.json`
- `.codex-orchestrator/runs/<run_id>/context.json`
- `.codex-orchestrator/runs/<run_id>/state.json`

Headless behavior is described in
[../references/headless-runner.md](../references/headless-runner.md).

### Prompt

`prompt` produces a fresh-session prompt from the plan/spec/docs. It does not
execute tasks and does not write learning events. The output prompt must still
include execution requirements for state, context snapshots, learning logs,
risk-scaled verification, and completion audit.

Prompt export uses
[../templates/fresh-session-prompt.txt](../templates/fresh-session-prompt.txt)
and is checked with
[../references/prompt-export-checklist.md](../references/prompt-export-checklist.md).

### Handoff

`handoff` produces a continuation prompt for an existing run. It must use an
explicit state path, run id, or unambiguous active run. It should preserve the
same source-grounding and completion-proof expectations as a fresh run.

## Dirty Worktree Policy

Dirty worktree classification happens after plan parsing because the parser
defines declared task files.

- unrelated dirty files: continue if they are outside the declared task files
- related dirty files: stop before touching them
- ambiguous related changes: stop and report the blocker

This protects user work without forcing a clean repository for unrelated edits.

## Task Contract Gate

Before any task edit, the executor must state and record:

- `scope`
- `files_to_inspect`
- `allowed_edits`
- `forbidden_edits`
- `acceptance_command_or_honest_substitute`

The same contract is stored under the task entry in state. This makes a resumed
agent reconstruct what was allowed even if the conversation context is gone.

## Context Health

`context_health` is stored in `.codex-orchestrator/runs/<run_id>/state.json`.
It does not try to measure remaining tokens. It answers whether another agent
can continue from durable artifacts without relying on hidden chat context.

The executor refreshes it after `context.json` creation, after each task or
phase, after blocker/error events, before handoff/resume, and before final
completion.

Valid statuses:

- `green`: state and artifacts are enough to resume; no open questions.
- `yellow`: execution can continue, but assumptions or open questions remain.
- `red`: safe continuation needs a blocker, user decision, or handoff.

Finished runs require `context_health.handoff_ready=true` and a non-red status.
Blocked or failed runs must leave a concrete `next_action`.

## Risk-Scaled Verification

Each task is classified as `low`, `mid`, or `high`.

- `low`: isolated file or module
- `mid`: multiple files, shared config, repeated edits to the same file, or
  unclear verification
- `high`: cross-area API, schema, auth, persistence, workflow, or breaking
  change

High-risk tasks require a compact high-risk verification matrix when relevant.
Scenarios include malformed input, stale state or resume paths, dirty worktree
preservation, hung command behavior, misleading success output or skipped tests,
and cancellation/interruption recovery. Irrelevant scenarios should be marked
`not-applicable` with a concrete reason.

## Completion Gate

Successful execution is not just "tests passed." A terminal successful run must
write:

- `lifecycle_outcome=finished`
- `context_health.handoff_ready=true`
- `context_health.status` is not `red`
- `completion_audit.passed=true`
- non-empty `completion_audit.prompt_to_artifact_checklist`
- non-empty `completion_audit.verification_evidence`

Blocked, failed, interrupted, or user-question outcomes use a non-success
`lifecycle_outcome` and a concrete `handoff_reason`.

`scripts/validate_state.py` enforces the mechanical parts of this contract.

## Boundaries

The executor intentionally stays skill-local:

- no imported `oh-my-codex` runtime
- no tmux/HUD/native hook requirement
- no default subagent dispatch
- no mandatory full adversarial QA for every task
- no repository-local learning log

The purpose is to keep Codex App execution predictable while preserving the
highest-value workflow safeguards.
