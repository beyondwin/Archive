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
  "context_snapshot_path": ".codex-orchestrator/runs/20260513T142233Z-archive-codex-example-7e884a0-a1b2c3/context.json",
  "context_basis_hash": "<sha256-of-source-list>",
  "context_health": {
    "status": "green",
    "last_checked_at": null,
    "context_snapshot_present": true,
    "context_basis_hash_recorded": true,
    "active_task_contract_present": false,
    "next_action": "Record the next task execution contract.",
    "open_questions": [],
    "known_assumptions": [],
    "handoff_ready": true
  },
  "test_command": "pytest",
  "baseline": {"status": "unknown", "summary": ""},
  "current_task": "task_0",
  "current_phase": "preflight",
  "lifecycle_outcome": null,
  "handoff_reason": "",
  "completion_audit": null,
  "risk_levels": {},
  "tasks": {},
  "execution_dag": [],
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

`context_snapshot_path` is required for `interactive` and `headless` execution
after preflight initializes. It must equal
`.codex-orchestrator/runs/<run_id>/context.json`. `context_basis_hash` must be
non-empty and match the `basis_hash` inside that snapshot. `prompt` and
`handoff` modes may omit these fields.

`context_health` is required for `interactive` and `headless` execution after
preflight initializes. It is a compact answer to: "Can another agent resume
from state without relying on hidden chat context?"

```json
"context_health": {
  "status": "green",
  "last_checked_at": "2026-05-14T00:00:00Z",
  "context_snapshot_present": true,
  "context_basis_hash_recorded": true,
  "active_task_contract_present": true,
  "next_action": "Run final verification and write completion_audit.",
  "open_questions": [],
  "known_assumptions": [],
  "handoff_ready": true
}
```

Rules:

- `status` must be `green`, `yellow`, or `red`.
- `next_action` must be a non-empty string.
- `open_questions` and `known_assumptions` must be arrays.
- `context_snapshot_present` must be true when `context_snapshot_path` exists.
- `context_basis_hash_recorded` must be true when `context_basis_hash` exists.
- `green` status cannot have open questions.
- `red` status cannot be `handoff_ready=true`.
- `lifecycle_outcome=finished` requires `handoff_ready=true` and not `red`.

`lifecycle_outcome` is the terminal handoff state and must not be confused with
`current_phase`. Valid values are `finished`, `blocked`, `failed`,
`userinterlude`, and `askuserQuestion`.

Successful terminal runs use:

```json
"lifecycle_outcome": "finished",
"handoff_reason": "",
"completion_audit": {
  "passed": true,
  "prompt_to_artifact_checklist": [
    "Task 0 changed docs/example.md as requested"
  ],
  "verification_evidence": [
    {"command": "pytest tests/example_test.py", "status": "passed"}
  ],
  "open_gaps": [],
  "residual_risk": []
}
```

Blocked, failed, interrupted, or user-question outcomes may omit a passing
`completion_audit`, but must set a concrete `handoff_reason`.

Optional `execution_dag` entries record parsed dependency metadata only. They do
not change task status semantics or bypass per-task execution contracts:

```json
"execution_dag": [
  {"id": "task_1", "depends_on": ["task_0"]}
]
```

## Per-Task Fields

```json
{
  "status": "pending",
  "title": "Task title",
  "risk": "low",
  "risk_reason": "single docs file",
  "files_declared": [],
  "files_changed": [],
  "depends_on": [],
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
- `depends_on` when parsed from the plan
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

For `risk=high`, task `verification` may include compact high-risk verification
matrix evidence:

```json
{
  "type": "high_risk_matrix",
  "scenario": "misleading_success_output",
  "status": "passed",
  "evidence": "raw/task_1-misleading-success.txt"
}
```
