# Headless Runner

Use this only for `mode=headless`, eval, CI, or explicitly detached execution.

## Safe Default Command

```bash
mkdir -p "$WORKTREE_ABS/.codex-orchestrator"
HEADLESS_SANDBOX="${HEADLESS_SANDBOX:-workspace-write}"

codex exec \
  --cd "$WORKTREE_ABS" \
  --sandbox "$HEADLESS_SANDBOX" \
  --json \
  --output-last-message "$WORKTREE_ABS/.codex-orchestrator/headless-final.md" \
  "$PROMPT" \
  > "$WORKTREE_ABS/.codex-orchestrator/headless.jsonl" 2>&1
```

## Schema Output Variant

```bash
mkdir -p "$WORKTREE_ABS/.codex-orchestrator"
HEADLESS_SANDBOX="${HEADLESS_SANDBOX:-workspace-write}"

codex exec \
  --cd "$WORKTREE_ABS" \
  --sandbox "$HEADLESS_SANDBOX" \
  --json \
  --output-schema "$WORKTREE_ABS/.codex-orchestrator/final.schema.json" \
  --output-last-message "$WORKTREE_ABS/.codex-orchestrator/headless-final.json" \
  "$PROMPT" \
  > "$WORKTREE_ABS/.codex-orchestrator/headless.jsonl" 2>&1
```

## Required Artifacts

- `.codex-orchestrator/headless.jsonl`
- `.codex-orchestrator/headless-final.md` or
  `.codex-orchestrator/headless-final.json`
- `.codex-orchestrator/state.json`
- raw verification output paths for failures

## Learning Log

Headless artifacts remain under `.codex-orchestrator/`. Learning events are
separate user-local records written to:

```text
~/.codex/learning/kws-codex-plan-executor/events.jsonl
```

Use `references/learning-log.md` and `scripts/append_learning_event.py` for
`blocker`, `error`, `verification_failure`, `recurring_issue`,
`successful_workaround`, and actionable `completion_learning` events. `prompt`
and `handoff` are not logging modes.

## Sandbox Selection

`headless_sandbox=workspace-write` is the default for implementation runs.
`headless_sandbox=read-only` is only for preflight, parse, or prompt
verification. If a read-only headless run reaches a task that requires editing,
stop with a blocker instead of silently switching sandbox mode.

## Eval Harness Boundary

When the outer eval harness invokes headless mode, it runs
`evals/check_execution.py` after the target execution finishes. The target
execution must not inspect fixture YAML, baseline files, `.harness` metadata,
or expected values. Use only the plan/spec/docs, state file, skill references,
and project files available in the test worktree.

## Hard Rule

Do not use `--dangerously-bypass-approvals-and-sandbox` unless the user
explicitly requested it and the run target is an isolated throwaway repository
or CI sandbox.
