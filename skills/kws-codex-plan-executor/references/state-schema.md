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
  "event_journal_path": ".codex-orchestrator/runs/20260513T142233Z-archive-codex-example-7e884a0-a1b2c3/events.jsonl",
  "last_event_seq": 1,
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
  "subagents_requested": false,
  "subagent_runs": [],
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

`event_journal_path` is project-local replay evidence for execution modes. For
`lifecycle_outcome=finished`, it must equal
`.codex-orchestrator/runs/<run_id>/events.jsonl`, and `last_event_seq` must be a
positive integer. The state validator checks only state metadata; journal file
contents are covered by `evals/check_event_journal.py`.

Optional top-level `drift` records the last drift reconciliation result:

```json
"drift": {
  "last_checked_at": "2026-05-16T07:35:00Z",
  "records": [],
  "unrepaired_blockers": []
}
```

When `lifecycle_outcome=finished`, `drift.unrepaired_blockers` must be empty
and `drift.records` cannot contain any record with `severity=blocking`.

Optional top-level `context_budget` mirrors the budget summary from
`context.json` when a run wants budget state in `state.json`:

```json
"context_budget": {
  "status": "green",
  "max_chars": 120000,
  "estimated_chars": 42100,
  "included_sections": [],
  "omitted_sections": []
}
```

`status` must be `green`, `yellow`, or `red`; `max_chars` must be positive;
`estimated_chars` must be non-negative; section fields must be arrays.

Optional top-level `subagents_requested` and `subagent_runs` record delegated
execution only when the user explicitly allowed subagents:

```json
"subagents_requested": true,
"subagent_runs": [
  {
    "id": "agent_123",
    "owner_task": "task_4",
    "mode": "fork_context",
    "write_scope": ["docs/**"],
    "status": "completed",
    "result_summary": "Updated delegated docs wording.",
    "changed_files": ["docs/example.md"],
    "review_status": "accepted",
    "merged_at": "2026-05-16T07:40:00Z",
    "overlap_rationale": "Parent task delegated one docs subset and reviewed before merge."
  }
]
```

Rules:

- `subagents_requested` is optional and defaults to false.
- Non-empty `subagent_runs` requires `subagents_requested=true`.
- Each `owner_task` must reference an existing task id.
- Each `write_scope` must be a non-empty list of path globs.
- Completed subagent records require `changed_files` and `review_status`.
- Completed `changed_files` must match the record's `write_scope`.
- `lifecycle_outcome=finished` cannot contain running or unreviewed subagent
  records.
- If a subagent `write_scope` overlaps the current task's allowed write scope,
  the record must include a non-empty `overlap_rationale`.

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
- Whenever any `context_health` field changes, update
  `context_health.last_checked_at` in the same state write.
- `lifecycle_outcome=finished` requires `context_health.last_checked_at` to be
  present and not older than `timestamps.updated_at` when `updated_at` is
  present. Active runs may carry older timestamps as advisory drift; validation
  only blocks terminal finished claims.

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

Optional top-level verification evidence may record scheduling decisions when
commands share mutable output resources:

```json
"verification": {
  "resource_serialization": [
    {
      "resource_key": "gradle-test:server:integrationTest:server/build/test-results/integrationTest",
      "commands": [
        "./server/gradlew -p server integrationTest --tests com.example.A",
        "./server/gradlew -p server integrationTest --tests com.example.B"
      ],
      "reason": "Gradle Test XML output is shared inside one worktree.",
      "decision": "serial"
    }
  ]
}
```

This evidence is informational unless a future scheduler enforces it. Use it to
explain why otherwise independent verification commands were not parallelized.

Optional top-level `method_audit` records whether required phase methods were
actually applied, missing, or waived:

```json
"method_audit": {
  "required": [
    "using-superpowers",
    "test-driven-development",
    "verification-before-completion"
  ],
  "applied": [
    {
      "skill": "test-driven-development",
      "phase": "implementation",
      "status": "applied",
      "evidence_refs": [
        "tasks.task_2.red_evidence",
        "tasks.task_2.green_evidence"
      ],
      "summary": "RED failed before implementation; GREEN passed after the fix."
    }
  ],
  "missing": [],
  "waived": []
}
```

Rules:

- Every skill in `method_audit.required` must appear in exactly one of
  `applied`, `missing`, or `waived`.
- `applied[].status` must be `applied`, and `applied[].evidence_refs` must be
  non-empty.
- `missing` entries fail validation when `lifecycle_outcome=finished`.
- `waived` entries must include a non-empty `reason`.
- `test-driven-development` applied during implementation must reference both
  RED and GREEN evidence.
- `review` applied during review must reference findings or an explicit
  no-findings residual-risk statement.
- `verification-before-completion` applied during verification must reference
  `completion_audit.verification_evidence`.
- `using-superpowers` applied as a gate must reference the task contract or
  pre-implementation state.

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
  "unit_manifest": {
    "unit_type": "execute-task",
    "context_mode": "focused",
    "required_skills": ["using-superpowers", "test-driven-development"],
    "tool_policy": "implementation",
    "allowed_write_globs": ["scripts/*.py", "evals/*.py"],
    "forbidden_write_globs": [".git/**", "graphify-out/**"],
    "artifact_policy": "inline-summary",
    "max_context_chars": 60000
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

Tasks may include optional `unit_manifest` while active. When
`lifecycle_outcome=finished`, every task whose status is `completed`,
`verified`, or `done` must include a valid manifest.

`unit_manifest` fields:

- `unit_type`: one of `research`, `plan`, `execute-task`, `reactive-execute`,
  `validate`, `complete`, `docs`, `review`, or `handoff`
- `context_mode`: one of `minimal`, `focused`, `expanded`, or `full`
- `required_skills`: array
- `tool_policy`: one of `read-only`, `planning`, `implementation`, `docs`, or
  `verification`
- `allowed_write_globs`: array
- `forbidden_write_globs`: array
- `artifact_policy`: one of `inline`, `inline-summary`, `excerpt`, or
  `on-demand`
- `max_context_chars`: positive integer

`implementation` manifests require non-empty `allowed_write_globs`. `read-only`
manifests must not allow write globs.

Tasks may include optional `carried_acceptance` when a sequential metric cannot
be fully resolved until a later task:

```json
"carried_acceptance": {
  "status": "open",
  "metric": "front index chunk size",
  "baseline_value": "208.78 kB after task_5",
  "current_value": "221.68 kB after task_6",
  "reason": "Host feature barrel remains statically reachable until task_7.",
  "depends_on_task": "task_7",
  "next_action": "Resolve host barrel coupling and rerun pnpm --dir front build."
}
```

Valid statuses are `open`, `resolved`, and `accepted_with_rationale`. `open` is
allowed during intermediate execution, but `lifecycle_outcome=finished` cannot
leave any carried acceptance entry open. Finished runs with `resolved` or
`accepted_with_rationale` carried acceptance must include final metric evidence
under `completion_audit.verification_evidence`.

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
