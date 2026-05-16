# Subagent Run Store

Subagent records are opt-in execution artifacts. They exist only when the user
explicitly requests subagents, delegation, parallel work, or passes
`subagents=on`.

Record shape:

```json
{
  "id": "agent_123",
  "owner_task": "task_4",
  "mode": "fork_context",
  "write_scope": ["docs/**"],
  "status": "completed",
  "result_summary": "Updated docs wording.",
  "changed_files": ["docs/example.md"],
  "review_status": "accepted",
  "merged_at": "2026-05-16T07:40:00Z"
}
```

Rules:

- `subagent_runs` requires explicit `subagents=on` or a recorded user request.
- Finished runs cannot have running, failed-without-review, or unreviewed
  subagent records.
- `changed_files` must match `write_scope`.
- Overlapping `write_scope` with another active subagent requires a rationale.

Subagent records are state artifacts, not a scheduler. The parent executor
still owns review, merge decisions, and final verification evidence.

