# State And Logging

State lives at `~/.codex/orchestrator/<run_id>/state.json`.

Execution artifacts live beside it:

- `context.json`
- `spec_manifest.json`
- `task_packets/task_<N>.json`
- `task_packets/task_<N>.md`
- `DECISIONS.md`
- `preflight_warnings.json`
- `trajectory.jsonl`
- `hooks/`
- `learning_events/`
- raw verification evidence
- headless result files

AgentLens events are best-effort. They never replace state and never block
implementation.

## Cache State

CPE may record prompt-cache audit and token telemetry fields in state:

```json
{
  "cache_strategy": {
    "mode": "interactive-default",
    "stable_prefix_policy": "static-first-hot-tail",
    "provider_cache_control": "unavailable",
    "prompt_audit_version": "1"
  },
  "cache_observations": [],
  "prompt_audit": {
    "last_checked_at": "2026-05-31T00:00:00Z",
    "stable_prefix_hashes": {},
    "stable_prefix_bytes": {},
    "dynamic_marker_violations": []
  }
}
```

Provider token counters are optional. Missing cache counters are stored as
`null`; they are not inferred as zero. Finished runs must have no prompt audit
dynamic-marker violations.

## Graphify And Dispatch Evidence

`graphify_audit` stores the output of
`scripts/check_graphify_freshness.py`. It records `Built from commit` freshness,
whether `graphify update .` ran, and whether tracked or ignored outputs changed.
Finished runs cannot retain Graphify audit errors, and must reference Graphify
audit evidence from `completion_audit.verification_evidence`.
When `graphify-out/` is tracked, a commit that contains only graphify outputs
after a successful update is still source-fresh; the checker treats that as
fresh because the indexed source corpus has not changed since the build commit.
If `graphify update .` reports no output changes, the checker also treats the
state as fresh when `--update-ran` is supplied.

`dispatch_decisions` stores `scripts/preflight_dispatch.py` output for
write-capable subagent tasks. Decisions are `delegate`, `local_fallback`, or
`block`; a finished run cannot retain an unresolved `block` decision.

`delegation_policy` stores the effective delegation policy for the run:
requested mode, request source, explicit user delegation intent, active spawn
policy, effective mode, and reason. It explains policy-level local fallback
without relying on prose-only state notes.

`preflight_bootstrap` stores the detection-only local environment report:
warnings, suggested bootstrap commands with `auto_run=false`, and environment
capabilities such as Node, Bun, pnpm, Gradle wrapper, Android SDK, adb, Cargo,
and AgentLens availability.

`command_cwd_evidence` records command provenance as command, cwd, phase, and
status. It must not store full logs, secrets, or transcripts.

`run_quality` stores or computes a compact quality summary for a run:
validation status, terminal state, stale flag, workspace/execution-worktree
match, schema drift, followups, and a short summary. Read-only inspection may
compute this without writing it back to state. Followups include markers such
as `stale_non_terminal_run`, `missing_execution_worktree`,
`plan_executability_fixable_issues`, and `full_spec_fallback_present`.
State-intrinsic operational debt is classified by
`scripts/run_quality_debt.py` so validation, static fixtures, and read-only
inspection use the same follow-up vocabulary.
Expected local fallback from an explicit-request-required spawn policy is
reported as `delegation_policy_expected_local_fallback`, not as prevented
delegation. `delegation_policy_prevented_all_delegation` is reserved for
explicit delegation requests that still fall back everywhere, and
`delegation_policy_missing_dispatch_evidence` flags finished write-capable
tasks without dispatch evidence.

## Failure, Recovery, And Progress

`current_blocker` is the machine-readable blocked-state record. It includes a
category, summary, recoverability flag, and next action kind. `blocked` outcomes
require a recoverable current blocker, while `finished` outcomes must clear it.

`failure_decision` records non-recoverable failure decisions for `failed`
outcomes. `recovery_attempts` records bounded retry/bootstrap attempts by root
signature; finished runs cannot retain open recovery attempts.

`scripts/repair_runs.py` is the operator repair path for stale CPE runs. Its
default mode emits a dry-run plan from recent `run_quality.open_followups`.
The apply mode requires one `--run-id`, one `--action`, and `--apply`; the only
mutating action is `mark-blocked-stale`. It rewrites only the selected
`state.json`, validates before and after the patch, and does not delete
worktrees or run directories.

`trajectory_path` points at an append-only JSONL projection. Events contain
sequence, event name, timestamp, task id, state ref, summary, evidence refs, and
redacted context budget metadata. Raw prompts are not stored there.

`progress_ledger` records per-task progress, stall count, last root signature,
next action, and whether operator input is needed.

## Human-Readable Task Surfaces

`task_packets/task_<N>.md` is generated from `task_packets/task_<N>.json` for
operator, handoff, prompt hot-tail, and subagent readability. It must preserve
files, task body, AC, verification, forbidden globs, context budget, decisions
count, and full-spec fallback warnings. The markdown view is never the source
of truth.

Completed tasks may record `next_task_summary`; `context_health` may carry
`hot_tail_summaries`. These are one-line hints for the next task and cannot
replace task status, dispatch strategy, acceptance evidence, verification
bundle evidence, or completion audit state.

## Plan Executability Audit

`plan_executability_audit` is copied from
`scripts/audit_plan_executability.py` output before task contracts or edits. It
keeps the path under `run_dir`, a `green|yellow|red` grade, and non-negative
blocking/fixable issue counts. The detailed JSON stays at
`$RUN_DIR/plan_executability_audit.json`; state stores the compact fields that
validation and run-quality debt need.

When operator review reduces blockers, state keeps both raw and effective
counts:

```json
{
  "plan_executability_audit": {
    "grade": "yellow",
    "raw_grade": "red",
    "blocking_issue_count": 0,
    "raw_blocking_issue_count": 2,
    "fixable_issue_count": 3,
    "raw_fixable_issue_count": 3,
    "operator_reviewed_blocking_issues": ["task_1:risk_marker_requires_operator_review"],
    "operator_decision": "Proceed locally after operator review."
  }
}
```

The audit is read-only. It classifies task packet readiness, acceptance
coverage, write-scope safety, risky paths, full-spec fallback, and expected
dispatch fit. Red audit results block execution before edits. Yellow audit
results may continue only when the operator records the decision and the
remaining issue is tracked through `run_quality.open_followups`.

## Structured Residual Risk And Replay

`completion_audit.residual_risk` remains list-shaped. Items may be strings or
structured residual risk objects with `owner`, `class`, `summary`,
`blocks_release`, optional `unblocks_when`, and optional `evidence_ref`. Valid
owners are `executor`, `operator`, `product`, and `environment`; valid classes
include `external_credentials`, `deployment`, `monitoring`,
`executor_evidence`, `environment_unavailable`, `product_followup`,
`environment_gap`, `test_scope_gap`, `third_party_drift`,
`manual_review_needed`, and `known_executor_debt`. A structured item with
`blocks_release=true` cannot coexist with a passed finished completion.

`completion_audit.verification_evidence` may also contain
`class=verification_bundle` objects. They record project-level command bundles
such as full eval, compile, shell syntax, and repository checks. Bundle
evidence is classified completion evidence; it does not replace the per-task
acceptance command.

`scripts/normalize_cpe_run.py` emits compact replay JSON for deterministic
checks and handoffs. It summarizes terminal state, completion status,
run-quality grade, open followups, full-spec fallback count, dispatch reason
counts, plan audit counts, residual risk classes, prompt/Graphify summaries,
and forbidden durable-output patterns without storing raw transcripts or full
prompts. `eval-coverage-cpe.md` maps this replay check and adjacent CPE quality
evals to the failure modes they protect.
