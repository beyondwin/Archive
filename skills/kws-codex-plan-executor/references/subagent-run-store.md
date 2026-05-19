# Subagent Run Store

Subagent records are opt-in execution artifacts. They exist only when the user
explicitly requests subagents, delegation, parallel work, or passes
`subagents=on`. `subagents=auto` does not by itself authorize spawning.

Record shape:

```json
{
  "id": "agent_123",
  "owner_task": "task_4",
  "mode": "fork_context",
  "task_packet_path": "~/.codex/orchestrator/run/task_packets/task_4.json",
  "state_path": "~/.codex/orchestrator/run/state.json",
  "write_scope": ["docs/**"],
  "verification_expectation": "Run docs validation for task_4.",
  "status": "completed",
  "result_summary": "Updated docs wording.",
  "changed_files": ["docs/example.md"],
  "review_status": "accepted",
  "merged_at": "2026-05-16T07:40:00Z"
}
```

Rules:

- `subagent_runs` requires explicit `subagents=on`, `delegation`, `parallel
  work`, `subagents`, or another recorded user request. Empty
  `subagent_runs` may appear with `subagents_requested=false`.
- `owner_task` must reference a task in state.
- Delegated workers receive only task id, task packet path, state path, write
  scope, and verification expectation; they do not receive raw full-plan
  context.
- `write_scope` must be a non-empty list of globs owned by that delegated run.
- Completed records require `changed_files` and `review_status`.
- Completed `changed_files` must match `write_scope`.
- Finished runs cannot have running, failed-without-review, or unreviewed
  subagent records.
- Overlapping `write_scope` with the current task requires an
  `overlap_rationale`, because the parent executor still owns merge review and
  final verification.
- Overlapping `write_scope` between multiple active subagents also requires a
  rationale before dispatch.

Subagent records are state artifacts, not a scheduler. The parent executor
still owns review, merge decisions, post-diff and state review before accepting
subagent output, and final verification evidence.
