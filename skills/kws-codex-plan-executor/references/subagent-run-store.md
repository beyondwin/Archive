# Subagent Run Store

Subagent records are execution artifacts, not a scheduler or a second source
of truth. State remains authoritative at
`~/.codex/orchestrator/<run_id>/state.json`.

`subagents=on` is the adaptive subagent-first default. The executor first runs
the pre-dispatch decision, then either delegates from a task packet or records a
local fallback on the task. `subagents=auto` does not by itself authorize spawning
unless the user explicitly requests subagents, delegation, or parallel work.

There are three related state surfaces:

- `subagent_runs`: concrete worker records for attempted delegated work.
- task `subagent_strategy`: the accepted per-task decision for completed
  write-capable tasks.
- `dispatch_decisions` and `delegation_policy`: deterministic pre-dispatch
  evidence from `scripts/preflight_dispatch.py`.

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

## Record Fields

Every `subagent_runs[]` item requires:

- `id`
- `owner_task`
- `mode`
- `write_scope`
- `status`
- `result_summary`

Valid `status` values are `queued`, `running`, `completed`, `failed`, and
`cancelled`.

Completed records also require:

- `changed_files`
- `review_status`

Valid `review_status` values are `unreviewed`, `accepted`, `rejected`, and
`changes_requested`.

Optional but important fields:

- `task_packet_path`: the task packet given to the worker.
- `state_path`: the authoritative state file path.
- `verification_expectation`: the command or evidence expected from the worker.
- `overlap_rationale`: required before accepting overlap with the current task
  or running overlapping active subagents.
- `merged_at`: timestamp for parent-accepted merge/reconciliation.

## State Rules

- `subagent_runs` requires `subagents_requested=true`, which is the default for
  `subagents=on` runs. Empty `subagent_runs` may appear with
  `subagents_requested=false` for `subagents=off` or conservative auto runs.
- `owner_task` must reference a task in state.
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

## Strategy Rules

In finished v2.20+ runs with `subagents_requested=true`, each completed
write-capable task records `subagent_strategy`.

Delegated strategy:

```json
{
  "mode": "delegated",
  "run_ids": ["agent_123"],
  "reason": "all pre-dispatch prerequisites passed"
}
```

- `run_ids` must reference reviewed, completed, accepted `subagent_runs` owned
  by the same task.
- The parent executor still performs post-diff and state review before
  accepting the run.

Local fallback strategy:

```json
{
  "mode": "local_fallback",
  "run_ids": [],
  "reason": "adaptive_policy_local_fast_path_docs_only"
}
```

- `run_ids` must be empty.
- `reason` must explain the failed prerequisite, safety reason, policy reason,
  or adaptive local fast path.
- Adaptive local fast path is not a failed dispatch. It is a deterministic
  policy decision for small, low-risk, low-parallel-value tasks.

Known adaptive local fast path reasons:

- `adaptive_policy_local_fast_path_small_scope`
- `adaptive_policy_local_fast_path_docs_only`
- `adaptive_policy_local_fast_path_linear_task`
- `adaptive_policy_local_fast_path_low_parallel_value`

Policy/tool fallback reasons may include
`spawn_policy_requires_explicit_user_request`, `spawn_agent tool is unavailable
in this session`, `subagents=off requests local-only execution`, or another
concrete pre-dispatch prerequisite from `scripts/preflight_dispatch.py`.

## Pre-Dispatch Linkage

Before spawning for an eligible write-capable task, run
`scripts/preflight_dispatch.py` and store its output in `dispatch_decisions`.
The decision is one of:

- `delegate`: safe and useful to spawn from the task packet.
- `local_fallback`: run locally and record task `subagent_strategy`.
- `block`: do not execute until the safety issue is resolved.

Finished runs cannot retain unresolved `dispatch_decisions[].decision =
block`.

`delegation_policy` records the run-level policy evidence: requested mode,
requested source, explicit delegation intent, spawn policy, effective mode,
reason, and optional adaptive gate signals. When `value_gate=local_fast_path`,
the policy reason and task `subagent_strategy.reason` should use the same known
adaptive reason.

## Worker Boundary

Delegated workers receive only:

- task id
- task packet path
- state path
- write scope
- verification expectation

They do not receive raw full-plan context and must not infer write ownership
from the full plan. The parent executor owns merge decisions, post-diff review,
state review, reconciliation, and final verification evidence.
