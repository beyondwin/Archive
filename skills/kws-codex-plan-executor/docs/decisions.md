# Decisions

| Decision | Outcome |
| --- | --- |
| Worktree location | Use `~/.codex/worktrees/<run_id>` so repository code and executor state are separated. |
| Orchestrator location | Use `~/.codex/orchestrator/<run_id>` for state and runtime artifacts. |
| Subagent default | Default on; `subagents=off` is the local-only escape hatch. |
| Prompt modes | Export-only; no filesystem side effects. |
