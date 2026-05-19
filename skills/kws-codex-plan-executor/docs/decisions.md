# Decisions

| Decision | Outcome |
| --- | --- |
| Worktree location | Use `~/.codex/worktrees/<run_id>` so repository code and executor state are separated. |
| Orchestrator location | Use `~/.codex/orchestrator/<run_id>` for state and runtime artifacts. |
| Subagent default | `subagents=on`; spawning remains task-packet-scoped, `subagents=off` is local-only, and `subagents=auto` is conservative explicit-request mode. |
| Prompt modes | Export-only; no filesystem side effects. |
