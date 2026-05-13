# Architecture - kws-codex-plan-executor

Runtime instructions live in `SKILL.md`. This file records the stable design.

## Purpose

`kws-codex-plan-executor` is the forward Codex-native entrypoint for plan
execution and prompt export. It replaces day-to-day use of
`kws-new-session-plan-prompt-gpt-5-5` without deleting the old compatibility
entrypoint.

## Modes

- `interactive`: default, current-session execution with visible progress.
- `headless`: explicit `codex exec` run for eval, CI, or detached execution.
- `prompt`: legacy fresh-session prompt export.
- `handoff`: continuation prompt export for resuming an existing run.

## Runtime Flow

1. Resolve paths and mode.
2. Validate plan structure with `scripts/parse_plan.py` for execution modes.
3. Initialize or update `.codex-orchestrator/state.json`.
4. Execute tasks locally unless subagents were explicitly requested.
5. Verify each task with risk-scaled commands and record failures with stable
   `ISSUE_KEY` values.
6. Validate state and summarize changed files, verification, resources, and
   residual risk.

## State File Contract

`.codex-orchestrator/state.json` is the source of truth for resuming execution.
The schema is documented in `references/state-schema.md` and mechanically
checked by `scripts/validate_state.py`.

## Subagent Policy

Subagents are opt-in only. The executor may use `spawn_agent` only when the user
explicitly asks for subagents, delegation, parallel work, or passes
`subagents=on`. Otherwise implementation, review, and verification are local to
the current Codex session.

## Headless Codex Exec Contract

Headless mode uses `codex exec --json --output-last-message` and defaults to
`--sandbox workspace-write`. It may use `--output-schema` for structured final
results. It does not use `--dangerously-bypass-approvals-and-sandbox` unless
the user explicitly asks and the target is isolated.

## Prompt Export Compatibility

Prompt export mode copies the old prompt-generator template behavior:
verified absolute paths, prompt-only output, conservative Spark evidence
packing, no-Spark removal, continuation ledger handling, risk-scaled
verification, and session-owned cleanup boundaries.

## Eval Surface

Deterministic scripts own mechanical correctness:

- `scripts/parse_plan.py`
- `scripts/validate_state.py`
- `evals/check_prompt.py`
- `evals/check_execution.py`

`evals/judge.md` is reserved for subjective quality after deterministic checks.

## Migration From kws-new-session-plan-prompt-gpt-5-5

The old skill is retained as a legacy wrapper. New prompt export usage should
call `kws-codex-plan-executor mode=prompt`. The old skill should not keep a
separate prompt-generation contract.
