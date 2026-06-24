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
  "cache_strategy": {
    "mode": "interactive-default",
    "stable_prefix_policy": "static-first-hot-tail",
    "provider_cache_control": "unavailable",
    "prompt_audit_version": "1"
  },
  "cache_observations": [],
  "prompt_audit": null,
  "graphify_audit": null,
  "dispatch_decisions": [],
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
- When `tasks` is non-empty, `current_task` references one of its task ids.
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
- In finished v2.20+ runs with `subagents_requested=true`, completed
  write-capable tasks must include `subagent_strategy`:
  - `mode=delegated`: `run_ids` references reviewed completed
    `subagent_runs` for the same task.
  - `mode=local_fallback`: `run_ids` is empty and `reason` explains the failed
    pre-dispatch prerequisite, safety reason, or adaptive local fast path
    reason.
- Cache fields are optional for older runs. When present,
  `cache_strategy.mode` is one of `interactive-default`,
  `headless-explicit`, `prompt-export`, or `handoff-export`; provider cache
  control is one of `unavailable`, `available-unused`, `available-enabled`, or
  `unknown`.
- Provider cache counters are telemetry only. Missing cache read/write counters
  are recorded as `null`, not zero.
- Finished runs cannot carry non-empty
  `prompt_audit.dynamic_marker_violations`.
- Finished `completion_audit.prompt_to_artifact_checklist`,
  `completion_audit.verification_evidence`, and
  `completion_audit.residual_risk` are lists. Use an empty `residual_risk` list
  when there is no known residual risk; do not store scalar strings.
- `graphify_audit` records deterministic freshness output from
  `scripts/check_graphify_freshness.py`. Finished runs cannot carry
  non-empty `graphify_audit.errors`, and must reference the Graphify evidence
  from `completion_audit.verification_evidence`.
- `plan_executability_audit` records read-only output from
  `scripts/audit_plan_executability.py`. When present, `path` must live under
  `run_dir`, `grade` is `green|yellow|red`, and issue counts are non-negative
  integers. Finished states cannot retain a red plan executability audit.
- `dispatch_decisions` records output from `scripts/preflight_dispatch.py`.
  Decisions are `delegate`, `local_fallback`, or `block`; finished runs cannot
  retain a `block` decision.
- `timestamps.started_at` and `timestamps.updated_at` are ISO timestamps.
  `timestamps.completed_at` is nullable while a run is active, but must be an
  ISO timestamp before `lifecycle_outcome=finished`.

v2.20 context-intelligence state may add per-task fields:

```json
{
  "task_0": {
    "task_packet_path": "<run_dir>/task_packets/task_0.json",
    "task_packet_sha256": "<sha256>",
    "spec_section_ids": ["S1"],
    "fallback_spec_used": false,
    "subagent_strategy": {
      "mode": "delegated",
      "run_ids": ["agent_123"],
      "reason": "Default subagent-first execution for an eligible task packet."
    },
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

v2.22 operational run quality state may add:

```json
{
  "source_workspace": "/repo/source",
  "execution_worktree": "/Users/example/.codex/worktrees/example-plan-20260519-143022",
  "command_cwd_evidence": [
    {
      "command": "python3 scripts/preflight_local_env.py --repo-root \"$WORKTREE_ABS\"",
      "cwd": "/Users/example/.codex/worktrees/example-plan-20260519-143022",
      "phase": "preflight",
      "status": "passed"
    }
  ],
  "delegation_policy": {
    "requested_mode": "on",
    "requested_source": "default",
    "explicit_user_delegation_request": false,
    "spawn_policy": "explicit-request-required",
    "effective_mode": "local_fallback",
    "reason": "spawn_agent tool policy requires explicit user delegation intent"
  },
  "preflight_bootstrap": {
    "schema_version": "1",
    "warnings": [],
    "bootstrap_plan": [],
    "environment_capabilities": {
      "node": "present",
      "bun": "present",
      "pnpm": "present",
      "gradle_wrapper": "absent",
      "android_sdk": "unknown",
      "adb": "absent",
      "cargo": "absent",
      "agentlens": "absent"
    }
  },
  "run_quality": {
    "schema_version": "1",
    "validation_status": "passed",
    "terminal_state": "finished",
    "stale": false,
    "workspace_matches_execution_worktree": true,
    "score": 92,
    "grade": "yellow",
    "schema_drift": [],
    "open_followups": ["agentlens_missing"],
    "operational_debt": {
      "schema_version": "1",
      "followups": ["agentlens_missing"],
      "count": 1,
      "blocking": false
    },
    "readiness": {"task_count": 1, "fixable_issue_count": 0, "blocking_issue_count": 0},
    "dispatch_consistency": {"mismatch_count": 0, "override_count": 0},
    "context_quality": {"full_spec_fallback_count": 0},
    "verification_quality": {"completion_audit_passed": true},
    "recommendations": [],
    "summary": "Run finished with validated state."
  },
  "plan_executability_audit": {
    "path": "/Users/example/.codex/orchestrator/example-plan-20260519-143022/plan_executability_audit.json",
    "grade": "yellow",
    "blocking_issue_count": 0,
    "fixable_issue_count": 1
  }
}
```

`execution_worktree`, when present, must equal `worktree` and end with
`.codex/worktrees/<run_id>`. `workspace` remains backward compatible; new
operator guidance should use `execution_worktree` as the command/edit boundary.
`run_quality.open_followups` may include actionable inspection markers such as
`stale_non_terminal_run`, `missing_execution_worktree`, and
`state_schema_drift`. Finished states that use v2.22 operational fields such as
`execution_worktree`, `delegation_policy`, or `preflight_bootstrap` must embed
`run_quality` with `readiness`, `dispatch_consistency`, `context_quality`, and
`verification_quality`; this keeps completion quality inspectable even after
the execution worktree is removed.

`run_quality.grade` is an operational quality grade, not a replacement for
`completion_audit.passed`. A finished run may have
`completion_audit.passed=true` and `run_quality.grade=yellow` when
implementation verification passed but non-blocking executor follow-up remains.

## Stale Blocked Repair

`scripts/repair_runs.py --apply --run-id <id> --action mark-blocked-stale`
may change a validated non-terminal stale run with a missing execution worktree
into a blocked run. The patch sets:

```json
{
  "lifecycle_outcome": "blocked",
  "current_phase": "recover",
  "handoff_reason": "Run <id> is stale and cannot resume because its execution worktree is missing.",
  "current_blocker": {
    "category": "state_integrity_drift",
    "summary": "Run <id> is stale and its execution worktree is missing.",
    "recoverable": true,
    "next_action_kind": "operator_decision"
  },
  "context_health": {
    "status": "yellow",
    "handoff_ready": true,
    "next_action": "Inspect the blocked state and start a fresh CPE run if implementation should continue."
  }
}
```

The repair also refreshes `timestamps.updated_at` and sets
`timestamps.completed_at` when it is absent. The script validates the original
state, validates the patched state, and writes only
`~/.codex/orchestrator/<run_id>/state.json`.

`delegation_policy.requested_source` is `default`, `explicit`,
`natural_language`, or `resume_state`. `spawn_policy` is `available`,
`unavailable`, `explicit-request-required`, or `unknown`. `effective_mode` is
`delegate`, `local_fallback`, `off`, or `blocked`.

Adaptive dispatch may add optional fields to `delegation_policy`:

- `policy_kind`: `adaptive` or `legacy`.
- `safety_gate`: `pending`, `passed`, or `failed`.
- `value_gate`: `pending`, `delegate`, `local_fast_path`, `block`, or `skipped`.
- `signals`: object with deterministic inputs such as declared file count,
  allowed write glob count, packet budget status, explicit delegation intent,
  and risk markers.

When a finished task's final `subagent_strategy` differs from the latest
non-block dispatch decision for that task, the task must include
`subagent_strategy_override` with `from_reason`, `to_reason`, `changed_at`,
`evidence`, and `operator_decision`. This is for stale or superseded dispatch
evidence only; it is not a way to bypass safety gates.

Known adaptive local fast path reasons are
`adaptive_policy_local_fast_path_small_scope`,
`adaptive_policy_local_fast_path_docs_only`,
`adaptive_policy_local_fast_path_linear_task`, and
`adaptive_policy_local_fast_path_low_parallel_value`. Finished runs may use
these reasons only when the task still records unit manifest, diff scope, and
verification evidence.

`preflight_bootstrap.bootstrap_plan` contains suggestions only. CPE must not run
those commands automatically.
