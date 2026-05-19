# Common Mistakes

- Implementing from `main` or the caller's original checkout.
- Writing executor state into the repository worktree.
- Treating prompt or handoff export as an execution mode.
- Forgetting that subagents default to on unless `subagents=off`.
- Marking a run finished while subagent work is still running or unreviewed.
- Reporting success without `completion_audit`, `context_health`, and
  verification evidence.
