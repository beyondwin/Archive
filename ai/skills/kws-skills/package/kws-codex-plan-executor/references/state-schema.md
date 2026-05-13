# State Schema

The executor writes `.codex-orchestrator/runs/<run_id>/state.json` in the active
worktree. This file is the resume source of truth for that run. Human-readable
checkpoints summarize state, but the JSON state owns task status.

For backwards compatibility, `.codex-orchestrator/state.json` may also be
updated as a latest-state copy or pointer. Do not use that root file as the
only active state when multiple runs exist.

Validate with:

```bash
python3 scripts/validate_state.py .codex-orchestrator/runs/<run_id>/state.json
```

## Top-Level Fields

```json
{
  "schema_version": "1",
  "run_id": "20260513T142233Z-archive-codex-example-7e884a0-a1b2c3",
  "mode": "interactive",
  "workspace": "/abs/path",
  "plan": "/abs/path/plan.md",
  "spec": "/abs/path/spec.md",
  "branch": "codex/example",
  "worktree": "/abs/path/worktree",
  "run_dir": ".codex-orchestrator/runs/20260513T142233Z-archive-codex-example-7e884a0-a1b2c3",
  "state_path": ".codex-orchestrator/runs/20260513T142233Z-archive-codex-example-7e884a0-a1b2c3/state.json",
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
- `run_id`
- `mode`
- `workspace`
- `plan`
- `branch`
- `worktree`
- `run_dir`
- `state_path`
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
  "contract": {
    "scope": "",
    "files_to_inspect": [],
    "allowed_edits": [],
    "forbidden_edits": [],
    "acceptance_command_or_honest_substitute": ""
  },
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
- `contract`
- `review_retries`
- `verifier_retries`

The `contract` object must include:

- `scope`
- `files_to_inspect`
- `allowed_edits`
- `forbidden_edits`
- `acceptance_command_or_honest_substitute`

Keep retry counts numeric, contract text fields as strings, and file lists as
arrays.
