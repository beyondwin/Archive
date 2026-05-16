# Pre-Dispatch Pipeline

The pre-dispatch pipeline is the gate sequence that runs before a task is
executed in interactive or headless mode. It keeps task execution deterministic
and blocks before edits when required state or policy is missing.

Gate order:

```text
1. version gate
2. state readability gate
3. worktree gate
4. dirty-file gate
5. context snapshot gate
6. context health gate
7. unit manifest gate
8. dispatch decision gate
9. event journal gate
10. task contract gate
```

Gate result shape:

```json
{
  "task_id": "task_2",
  "status": "passed",
  "checked_at": "2026-05-16T07:30:00Z",
  "gates": [
    {"name": "version", "status": "passed", "evidence": "skill version 1.9.0"},
    {"name": "state", "status": "passed", "evidence": "state schema valid"},
    {"name": "worktree", "status": "passed", "evidence": "branch codex/example"},
    {"name": "dirty-files", "status": "passed", "evidence": "no related dirty files"},
    {"name": "context", "status": "passed", "evidence": "context_health green"},
    {"name": "unit-manifest", "status": "passed", "evidence": "implementation policy"},
    {"name": "dispatch-decision", "status": "passed", "evidence": "task dependencies satisfied"},
    {"name": "event-journal", "status": "passed", "evidence": "events.jsonl seq 4"},
    {"name": "task-contract", "status": "passed", "evidence": "contract recorded in state"}
  ]
}
```

Any failed gate before edits blocks execution. Any failed gate after edits
requires a checkpoint with `lifecycle_outcome=blocked` or `failed` unless the
gate can be repaired safely and re-run.

## Gate Notes

The version gate records the executor contract version used for the task. The
state gate proves `.codex-orchestrator/runs/<run_id>/state.json` is readable and
valid enough to continue. The worktree gate proves execution is not happening
from `main` or the caller's original checkout.

The dirty-file gate compares current git changes to declared task files. The
context gates verify `context.json`, `context_basis_hash`, and `context_health`.
The manifest gate verifies task policy. The dispatch decision gate records
whether dependencies and subagent opt-in state allow the task to run.

The event journal gate verifies that project-local event evidence can be
recorded. The task contract gate records the five-line
`TASK EXECUTION CONTRACT` before edits.

