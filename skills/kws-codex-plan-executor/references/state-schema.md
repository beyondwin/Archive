# State Schema

State source of truth:

```text
~/.codex/orchestrator/<run_id>/state.json
```

Example:

```json
{
  "schema_version": "1",
  "run_id": "example-plan-20260519-143022",
  "mode": "interactive",
  "workspace": "/repo",
  "plan": "/repo/plan.md",
  "branch": "codex/example-plan-20260519-143022",
  "worktree": "/Users/example/.codex/worktrees/example-plan-20260519-143022",
  "run_dir": "/Users/example/.codex/orchestrator/example-plan-20260519-143022",
  "state_path": "/Users/example/.codex/orchestrator/example-plan-20260519-143022/state.json",
  "context_snapshot_path": "/Users/example/.codex/orchestrator/example-plan-20260519-143022/context.json",
  "context_basis_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "current_task": "task_0",
  "current_phase": "task_loop",
  "lifecycle_outcome": null,
  "handoff_reason": "",
  "completion_audit": null,
  "subagents_requested": true,
  "subagent_runs": [],
  "tasks": {},
  "risk_levels": {},
  "review_issue_keys": [],
  "verification": [],
  "session_owned_resources": [],
  "last_checkpoint": null,
  "timestamps": {
    "started_at": "2026-05-19T14:30:22Z",
    "updated_at": "2026-05-19T14:30:22Z",
    "completed_at": null
  }
}
```

Required path invariants:

- `run_dir` ends with `.codex/orchestrator/<run_id>`.
- `worktree` ends with `.codex/worktrees/<run_id>`.
- `state_path` equals `run_dir/state.json`.
- `context_snapshot_path`, when present, equals `run_dir/context.json`.
- Old local journal metadata is rejected; AgentLens metadata belongs in
  `agentlens_orchestration_run` and `last_agentlens_event_at`.
