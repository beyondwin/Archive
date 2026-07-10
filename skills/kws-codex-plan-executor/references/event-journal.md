# Event Journal

`events.jsonl` is the authoritative CPE v3 transition history. The runtime
appends one canonical JSON event while holding an exclusive file lock, flushes
and fsyncs it, then rebuilds and atomically replaces `state.json`.

Validation rejects sequence gaps, duplicate event IDs, predecessor mismatch,
hash mismatch, invalid transitions, and a stored projection that differs from
replay. Evidence is referenced by digest rather than embedded as raw prompt,
transcript, secret, or unbounded command output.

Repair never edits or truncates the journal. A safe state change is represented
by a compensating event; rebuilding the projection does not require a new event.

## Event Vocabulary

New runtime writes use only these typed events:

```text
run.status_changed
task.status_changed
task.retry_scheduled
attempt.started
attempt.completed
verdict.recorded
evidence.attached
worktree.revision_recorded
blocker.opened
blocker.updated
blocker.resolved
repair.applied
context.updated
completion.recorded
```

Historical schema-3 journals may contain `attempt.recorded`. Chain validation
and replay continue to accept it, but the append boundary rejects it for new
writes.

`worktree.revision_recorded` advances exactly one revision from the currently
projected value and carries a 64-character lowercase SHA-256 patch digest.
Future write controllers may also include `changed_files` and `attempt_id`.

Blockers use stable `blocker_id` values across `opened`, `updated`, and
`resolved`. Opening records category, owner, and resume condition, and may
record a root-cause key. Resolution requires evidence refs. Retrying a blocked
task is a separate `task.retry_scheduled` event with an explicit phase, root
cause, and worktree revision; no generic `blocked -> ready` transition is
inferred.
