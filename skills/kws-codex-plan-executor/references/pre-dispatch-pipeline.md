# Pre-Dispatch Pipeline

Before delegating work:

1. Parse the plan.
2. Confirm the current task has declared files.
3. Confirm dirty files do not overlap the task.
4. Confirm state is writable under `~/.codex/orchestrator/<run_id>/state.json`.
5. Assign each subagent a disjoint write scope.
6. Record the delegation in `subagent_runs`.
