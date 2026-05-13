# Headless Runner

Use this only for `mode=headless`, eval, CI, or explicitly detached execution.

## Safe Default Command

```bash
codex exec \
  --cd "$WORKTREE_ABS" \
  --sandbox workspace-write \
  --json \
  --output-last-message "$WORKTREE_ABS/.codex-orchestrator/headless-final.md" \
  "$PROMPT" \
  > "$WORKTREE_ABS/.codex-orchestrator/headless.jsonl" 2>&1
```

## Schema Output Variant

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

## Required Artifacts

- `.codex-orchestrator/headless.jsonl`
- `.codex-orchestrator/headless-final.md` or
  `.codex-orchestrator/headless-final.json`
- `.codex-orchestrator/state.json`
- raw verification output paths for failures

## Hard Rule

Do not use `--dangerously-bypass-approvals-and-sandbox` unless the user
explicitly requested it and the run target is an isolated throwaway repository
or CI sandbox.
