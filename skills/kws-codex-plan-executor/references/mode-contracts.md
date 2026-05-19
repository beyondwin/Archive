# Mode Contracts

## interactive

Create or resume a dedicated execution worktree at
`~/.codex/worktrees/<plan-slug>-<YYYYMMDD-HHMMSS>`. Keep all executor state in
`~/.codex/orchestrator/<run_id>/state.json`. Use subagents only when the user
explicitly requests delegation/parallel agent work or passes `subagents=on`;
`subagents=auto` without an explicit request remains local.

## headless

Use the same worktree and orchestrator layout as interactive mode. A headless
target must bootstrap required skills in its prompt, must not launch another
nested `codex exec`, and must write the structured headless result described by
`templates/headless-output-schema.json`.

When `CODEX_EVAL_HOME` is present, the current `codex exec --cd` repository is
the isolated execution workspace. Do not run `git worktree add` or write git
refs in that eval runtime; record the logical worktree path in state and write
orchestrator artifacts under `$CODEX_EVAL_HOME/.codex/orchestrator/<run_id>`.

## prompt

Export a fresh-session prompt only. Do not create worktrees, state, context
snapshots, hooks, logs, or task artifacts.

## handoff

Export a continuation prompt only. The prompt must include `HANDOFF CHECKPOINT`
and enough state path information for a future session to resume from
`~/.codex/orchestrator/<run_id>/state.json`.

## resume

`resume=latest` scans `~/.codex/orchestrator/*/state.json`. If more than one
active candidate exists, stop and ask which run to resume.
