# Pre-Dispatch Pipeline

Before delegating work:

1. Parse the plan.
2. Confirm the user explicitly requested subagents/delegation/parallel work or
   passed `subagents=on`.
3. Confirm the current task has declared files.
4. Confirm dirty files do not overlap the task.
5. Confirm state is writable under `~/.codex/orchestrator/<run_id>/state.json`.
6. Assign each subagent a disjoint write scope.
7. Record the delegation in `subagent_runs`.
