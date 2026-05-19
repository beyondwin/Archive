# Common Mistakes

- Implementing from `main` or the caller's original checkout.
- Writing executor state into the repository worktree.
- Treating prompt or handoff export as an execution mode.
- Treating `subagents=auto` as permission to spawn without an explicit user
  request; use default `subagents=on` when task-packet-scoped delegation should
  be permitted.
- Marking a run finished while subagent work is still running or unreviewed.
- Reporting success without `completion_audit`, `context_health`, and
  verification evidence.
