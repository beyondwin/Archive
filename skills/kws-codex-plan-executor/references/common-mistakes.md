# Common Mistakes

- Implementing from `main` or the caller's original checkout.
- Writing executor state into the repository worktree.
- Treating prompt or handoff export as an execution mode.
- Treating `subagents=auto` as permission to spawn without an explicit user
  request.
- Treating `subagents=on` as permission-only; eligible write-capable tasks are
  subagent-first and local fallback requires a task `subagent_strategy` reason.
- Marking a run finished while subagent work is still running or unreviewed.
- Reporting success without `completion_audit`, `context_health`, and
  verification evidence.
