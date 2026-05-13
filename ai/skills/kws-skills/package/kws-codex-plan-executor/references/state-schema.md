# State Schema

The executor writes `.codex-orchestrator/state.json` in the active worktree.
This file is the resume source of truth. Human-readable checkpoints summarize
state, but the JSON state owns task status.

Validate with:

```bash
python3 scripts/validate_state.py .codex-orchestrator/state.json
```

## Top-Level Fields

```json
{
  "schema_version": "1",
  "mode": "interactive",
  "workspace": "/abs/path",
  "plan": "/abs/path/plan.md",
  "spec": "/abs/path/spec.md",
  "branch": "codex/example",
  "worktree": "/abs/path/worktree",
  "test_command": "pytest",
  "baseline": {"status": "unknown", "summary": ""},
  "current_task": "task_0",
  "current_phase": "preflight",
  "risk_levels": {},
  "tasks": {},
  "review_issue_keys": {},
  "verification": {},
  "session_owned_resources": [],
  "last_checkpoint": null,
  "timestamps": {
    "started_at": null,
    "updated_at": null,
    "completed_at": null
  }
}
```

Required top-level fields:

- `schema_version`
- `mode`
- `workspace`
- `plan`
- `branch`
- `worktree`
- `current_task`
- `current_phase`
- `tasks`
- `timestamps`

`mode` must be one of `interactive`, `headless`, `prompt`, or `handoff`.

## Per-Task Fields

```json
{
  "status": "pending",
  "title": "Task title",
  "risk": "low",
  "risk_reason": "single docs file",
  "files_declared": [],
  "files_changed": [],
  "pre_task_sha": null,
  "commit": null,
  "review_retries": 0,
  "verifier_retries": 0,
  "issue_keys": [],
  "verification": [],
  "summary": "",
  "started_at": null,
  "completed_at": null
}
```

Required per-task fields:

- `status`
- `risk`
- `files_declared`
- `review_retries`
- `verifier_retries`

Keep retry counts numeric and file lists as arrays.
