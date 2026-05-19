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
  "spec_manifest_path": "/Users/example/.codex/orchestrator/example-plan-20260519-143022/spec_manifest.json",
  "task_packet_dir": "/Users/example/.codex/orchestrator/example-plan-20260519-143022/task_packets",
  "current_task_packet_path": "/Users/example/.codex/orchestrator/example-plan-20260519-143022/task_packets/task_0.json",
  "decisions_register": [],
  "preflight_warnings": [],
  "last_completed_task": null,
  "last_completed_at": null,
  "compaction": {
    "points": [],
    "last_compaction_after_task": null,
    "context_drop_count": 0
  },
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
- `spec_manifest_path`, when present, equals `run_dir/spec_manifest.json`.
- `task_packet_dir`, when present, equals `run_dir/task_packets`.
- `current_task_packet_path`, when present, lives under `task_packet_dir`.
- Old local journal metadata is rejected; AgentLens metadata belongs in
  `agentlens_orchestration_run` and `last_agentlens_event_at`.
- `subagents_requested` defaults to `true` because `subagents=on` is the
  default. Set it to `false` only for `subagents=off`, or for `subagents=auto`
  when there was no explicit user request for subagents/delegation/parallel
  work.

v2.20 context-intelligence state may add per-task fields:

```json
{
  "task_0": {
    "task_packet_path": "<run_dir>/task_packets/task_0.json",
    "task_packet_sha256": "<sha256>",
    "spec_section_ids": ["S1"],
    "fallback_spec_used": false,
    "timing": {
      "started": "2026-05-19T14:31:00Z",
      "completed": "2026-05-19T14:34:00Z",
      "verified": "2026-05-19T14:35:00Z"
    }
  }
}
```

When v2.20 fields are present, `decisions_register` and
`preflight_warnings` must be lists. Finished completed tasks must include
`timing.started` and `timing.completed`. `last_completed_task` is either null or
a task id in `tasks`.
