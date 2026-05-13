# Architecture - kws-codex-plan-executor

Runtime instructions live in `SKILL.md`. This file records the stable design.

## Purpose

`kws-codex-plan-executor` is the forward Codex-native entrypoint for plan
execution and prompt export. It fully replaces the former
`kws-new-session-plan-prompt-gpt-5-5` compatibility entrypoint.

## Modes

- `interactive`: default, current-session execution with visible progress.
- `headless`: explicit `codex exec` run for eval, CI, or detached execution.
- `prompt`: legacy fresh-session prompt export.
- `handoff`: continuation prompt export for resuming an existing run.

## Runtime Flow

1. Resolve paths and mode.
2. Validate plan structure with `scripts/parse_plan.py` for execution modes.
3. Initialize a `run_id` and update `.codex-orchestrator/runs/<run_id>/state.json`.
4. Record a task execution contract before edits.
5. Execute tasks locally unless subagents were explicitly requested.
6. Verify each task with risk-scaled commands and record failures with stable
   `ISSUE_KEY` values.
7. Validate state and summarize changed files, verification, resources, and
   residual risk.

## State File Contract

`.codex-orchestrator/runs/<run_id>/state.json` is the source of truth for
resuming one execution. `.codex-orchestrator/state.json` is retained only as a
latest-state compatibility copy or pointer. The schema is documented in
`references/state-schema.md` and mechanically checked by
`scripts/validate_state.py`.

## Learning Log Contract

Execution modes may append redacted notable-boundary events to a user-local
per-run log:

```text
~/.codex/learning/kws-codex-plan-executor/
  index.jsonl
  runs/<YYYY-MM-DD>/<run_id>/{meta.json,events.jsonl,final.json}
```

`run_id` is generated from UTC time, repo slug, branch slug, head hash, and a
random suffix. The helper lifecycle is `init-run`, `append`, and `close-run`.
Events include `run_id`, `execution.run_dir`, and `execution.state_path` so logs
from multiple projects or multiple same-project executors remain queryable and
do not logically mix. This log is for improving the executor across
repositories. It does not replace per-run state, checkpoints, headless logs, or
raw verification artifacts.

## Subagent Policy

Subagents are opt-in only. The executor may use `spawn_agent` only when the user
explicitly asks for subagents, delegation, parallel work, or passes
`subagents=on`. Otherwise implementation, review, and verification are local to
the current Codex session.

## Headless Codex Exec Contract

Headless mode uses `codex exec --json --output-last-message`, creates
`.codex-orchestrator/runs/<run_id>/` before redirecting logs, and defaults to
`--sandbox workspace-write`. `headless_sandbox=read-only` is limited to
preflight, parse, and prompt verification; implementation tasks stop instead of
silently switching sandbox mode. Headless mode may use `--output-schema` for
structured final results. It does not use
`--dangerously-bypass-approvals-and-sandbox` unless the user explicitly asks and
the target is isolated.

Headless runs are fresh Codex processes, so prompts must bootstrap applicable
skills rather than relying on parent-session state. Runtime prompts and eval
prompts explicitly require `using-superpowers`, and require
`test-driven-development` before implementation of features, bug fixes,
refactors, or behavior changes.

The supervising session owns the `codex exec` launch. Once the target process
starts, `mode=headless` means it writes headless artifacts while executing
locally; it must not recurse into another nested `codex exec`.

The eval harness creates real headless worktrees for resume and dirty-worktree
scenarios. `initial_state` is written before the bootstrap commit, while
`dirty_files` are written after the commit so `git status` exposes them as user
dirty work. The target run is forbidden from reading fixture YAML, baselines,
`.harness` metadata, or expected values; the outer harness performs final
fixture checks.

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
- `evals/check_parse_plan.py`
- `evals/check_state_schema.py`
- `evals/check_learning_log.py`
- `evals/check_skill_contract.py`

`evals/judge.md` is reserved for subjective quality after deterministic checks.

Dynamic execution fixtures now cover:

- `resume=latest` preferring persisted state over a conflicting plan.
- unrelated dirty worktree files being preserved while execution continues.
- related dirty task files blocking before edits.
- interactive success runs recording the task execution contract in state.

## Migration From Legacy Prompt Export

The old `kws-new-session-plan-prompt-gpt-5-5` skill has been removed from the
package. Prompt export usage should call `kws-codex-plan-executor mode=prompt`.
