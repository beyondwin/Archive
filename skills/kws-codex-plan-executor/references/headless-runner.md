# Headless Runner

Headless mode runs the same executor contract in a fresh process.

```bash
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
RUN_ID="${PLAN_SLUG}-$(date -u +%Y%m%d-%H%M%S)"
WORKTREE="$CODEX_HOME/worktrees/$RUN_ID"
RUN_DIR="$CODEX_HOME/orchestrator/$RUN_ID"
STATE_PATH="$RUN_DIR/state.json"
mkdir -p "$CODEX_HOME/worktrees" "$RUN_DIR/hooks" "$RUN_DIR/learning_events"
```

Before task execution, create the git worktree under `$WORKTREE`; if the branch
name already exists, append the run_id or another unique suffix. Do not implement from `main`.
Do not implement from the caller's original checkout.

The headless prompt must include `using-superpowers` and
`test-driven-development`, must explain that this is not a headless-only rule,
and must instruct the target: `Do not launch another nested codex exec`.
Do not launch another nested `codex exec`.

Respect `HEADLESS_SANDBOX`, with supported values `workspace-write` and
`read-only`. In `read-only`, run preflight and prompt verification only.

Write final JSON using `templates/headless-output-schema.json` with `status`,
`run_id`, `state_path`, `changed_files`, `verification`, `open_gaps`,
`residual_risk`, and `next_action`.
