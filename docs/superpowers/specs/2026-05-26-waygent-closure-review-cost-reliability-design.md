# Waygent Closure, Review, and Cost Reliability Hardening

- **Date**: 2026-05-26
- **Type**: Brainstorming-approved design spec
- **Status**: Approved design, pending implementation plan
- **Scope**: Waygent run closure, recovered-failure projection, review loop
  integration, repair-first recovery, cost controls, provider adapter hygiene,
  and stale-run cleanup
- **Next artifact**: implementation plan via `superpowers:writing-plans`

## 1. Goal

Waygent should feel at least as reliable as the current
`subagent-driven-development` workflow while keeping its product-runtime
advantages: isolated worktrees, durable state, checkpoint artifacts, Lens
projections, apply authority, and operator-facing explanations.

The current failure pattern is narrower and more specific than "agents make
mistakes." Workers often produce useful code and verification evidence, but the
Waygent runtime can still leave the run blocked because:

- old failure events are still projected as current blockers after later
  recovery succeeds;
- recovery can make review evidence mandatory without dispatching or recording
  the review evidence needed to satisfy the audit;
- `missing_apply_ready_evidence` hides the actual missing requirement;
- trust projection treats recovered failures and active failures the same;
- full worker retries are still too expensive when a small repair would work;
- stale `running` runs, adapter failures, and malformed provider output need a
  safer closeout story.

This spec defines a three-milestone hardening program:

- **P0 - Closure-first hardening**: make current blockers, apply readiness,
  trust, and explain output reflect the latest durable state.
- **P1 - Review loop integration**: bring the successful parts of
  `subagent-driven-development` into Waygent as an artifact-first task review
  lifecycle.
- **P2 - Cost and adapter hygiene**: reduce expensive retry loops and make
  provider/runtime failures cheaper to diagnose, repair, or clean up.

## 2. Current Evidence

Local run evidence under `~/Library/Application Support/waygent/runs` showed
the reliability gap:

- 80 run states were found.
- 70 runs were `blocked`.
- 8 runs were still `running`.
- 2 runs were `completed`.
- Apply blockers included:
  - `intake_decision_required`: 15 runs
  - `dirty_source_checkout`: 8 runs
  - `missing_apply_ready_evidence`: 5 runs
- Event failure classes included:
  - `verification_failed`: 150
  - `malformed_result`: 48
  - `adapter_crashed`: 38
  - `environment_blocker`: 19
  - `diff_scope_failed`: 19
  - `missing_checkpoint`: 4
  - `dependency_missing`: 3
  - `command_not_found`: 3
  - `timeout`: 2
- The recorded cost ledger total across local run states was about
  `$7,641.78`.

The most recent inspected run,
`readmates_admin_vnext_s2_platform_ops_health_20260525_162107`, exposed a
representative closure defect:

- all five tasks reached `status: "verified"`;
- each task had a checkpoint ref;
- combined apply evidence existed and had `status: "passed"`;
- verification reruns passed for all tasks;
- the run still blocked apply with `missing_apply_ready_evidence`;
- `explain` reported `verification_failed`, even though the latest
  verification evidence passed;
- the actual audit blocker was review evidence required after recovery:
  `review_evidence:recovery_attempted`.

That state is technically safe because Waygent does not apply without evidence,
but it is operationally poor. The operator sees the wrong blocker and cannot
tell whether to rerun verification, request review, repair a task, or clean up a
stale run.

## 3. Design Principles

### 3.1 Latest durable state beats old events

Event journals are append-only evidence, not the final truth by themselves.
Current status projections must resolve old failures against later success
events, state task status, recovery records, checkpoint evidence, and
completion audit results.

### 3.2 "Blocked" must name the missing contract

`missing_apply_ready_evidence` is allowed only as a last-resort fallback. When
Waygent knows the missing contract, it must surface the precise blocker:

- `review_evidence_missing`
- `completion_audit_failed`
- `stale_verification_failure`
- `combined_apply_evidence_missing`
- `checkpoint_not_apply_ready`
- `state_reconciliation_failed`
- `terminal_invariant_failed`
- `cost_budget_exhausted`
- `provider_output_malformed`
- `adapter_crashed`

### 3.3 Recovery creates a review obligation and a review path

If recovery makes review mandatory, the runtime must either dispatch the review
workers automatically or stop in an explicit `review_required` state. It must
not leave the operator with a generic apply-readiness blocker.

### 3.4 Repair before full retry

When a worker produced a useful patch and verification failed, the default next
move is scoped repair on top of the prior diff. Full worker respawn is a
fallback for missing or unusable patch evidence, not the first choice.

### 3.5 Cost is evidence

Cost, attempts, retries, cached-token usage, and provider runtime are operator
evidence. They should influence recovery decisions and be visible in explain,
status, API, and console surfaces.

### 3.6 Runtime remains the apply authority

No host chat, KWS executor skill, or manual subagent workflow applies Waygent
patches on Waygent's behalf. The runtime remains the source of scheduling,
checkpoint, review, audit, apply, and Lens emission.

## 4. Non-Goals

- Replacing Waygent with `subagent-driven-development`.
- Reintroducing legacy Python AgentLens or KWS CPE/CME routing.
- Changing the durable `agentlens.event.v3` event contract label.
- Making root `docs/superpowers/*` canonical runtime documentation.
- Adding cloud CI or hosted services.
- Applying blocked run patches automatically without explicit apply readiness.
- Solving every possible provider failure. This spec covers the repeated
  failure classes observed in recent runs.

## 5. Target Lifecycle

Waygent task execution becomes a closed artifact loop:

```text
intake
  -> plan preflight
  -> safe wave selection
  -> implement
  -> verify
  -> repair when needed
  -> spec review when required
  -> quality review when required
  -> checkpoint
  -> combined apply dry-run
  -> completion audit
  -> ready_to_apply
  -> apply
```

The important change is not that every task always needs every phase. The
change is that every phase which becomes required has a first-class state,
artifact, event, and operator decision.

## 6. P0 - Closure-First Hardening

### 6.1 Stale verification resolution

Current behavior can report `verification_failed` when any historical
`runway.verification_result` failed, even if later verification passed. P0
adds a resolver that computes verification status per task:

```ts
interface TaskVerificationResolution {
  task_id: string;
  latest_status: "passed" | "failed" | "missing";
  latest_verification_ref: string | null;
  stale_failure_refs: string[];
}
```

Rules:

1. Use state verification records and verification events together.
2. Group by `task_id`.
3. Prefer the latest `verified_at` or event sequence for that task.
4. A task with latest pass and `task.status === "verified"` is not blocked by
   older failed verification records.
5. Keep stale failure refs in evidence packets so operators can audit the
   recovery history.

Surfaces:

- `projectOperatorDecision` uses the resolver before emitting
  `verification_failed`.
- `projectTrustReport` separates active failures from recovered failures.
- `waygent explain` reports `recovered_failures` when useful, but does not make
  them primary blockers.

### 6.2 Completion audit blocker taxonomy

`projectApplyReadinessFromState` reads completion audit blockers and returns a
precise reason:

```ts
type ApplyReadinessReason =
  | "ready"
  | "review_evidence_missing"
  | "completion_audit_failed"
  | "terminal_invariant_failed"
  | "state_reconciliation_failed"
  | "combined_apply_evidence_missing"
  | "combined_apply_patch_missing"
  | "checkpoint_not_apply_ready"
  | "state_drift"
  | "missing_apply_ready_evidence";
```

Mapping examples:

- residual risk starts with `review_evidence:` ->
  `review_evidence_missing`
- terminal invariant blocker exists -> `terminal_invariant_failed`
- completion audit lacks combined evidence -> `combined_apply_evidence_missing`
- checkpoint manifest exists but dry-run failed -> `checkpoint_not_apply_ready`

The Lens operator decision projection turns these reasons into first-class
operator blockers with targeted actions. For example,
`review_evidence_missing` recommends `run_review`, not `rerun_verification`.

### 6.3 Trust projection distinguishes active and recovered failures

`projectTrustReport` changes from "any failed or blocked event means failed" to
a resolved model:

```ts
interface TrustReport {
  trust_status: "trusted" | "failed" | "insufficient_evidence" | "needs_review";
  active_failure_count: number;
  recovered_failure_count: number;
  evidence_score: number;
  reasons: string[];
}
```

Rules:

- Active task failure, active apply blocker, unrepaired drift, or failed latest
  verification keeps `trust_status: "failed"`.
- Recovered failure history contributes to `recovered_failure_count`, not
  failure status.
- A recovery record with no required review evidence yields
  `trust_status: "needs_review"`.
- Passed verification plus passed audit and no active blockers yields
  `trust_status: "trusted"`.

### 6.4 Explain and API consistency

`waygent explain`, `waygent inspect`, `apps/api`, and `apps/console` consume
the same operator decision projection. P0 adds contract tests that assert the
same primary blocker for:

- CLI explain output;
- API run detail;
- console UI model;
- Lens operator decision projection.

## 7. P1 - Review Loop Integration

### 7.1 Review roles

Waygent adds two runtime roles:

```ts
type ProviderRole =
  | "coordinator"
  | "implementer"
  | "repair"
  | "spec_reviewer"
  | "quality_reviewer"
  | "verifier";
```

The roles mirror the useful shape of `subagent-driven-development`:

- implementer builds the requested task;
- spec reviewer checks whether the implementation matches the task/spec;
- quality reviewer checks maintainability, tests, and local patterns;
- repair worker performs tight fixes from evidence.

### 7.2 Review requirement policy

Review is required when any condition is true:

- task risk is `high`;
- task has broad file claims;
- task had recovery;
- task had a malformed result or adapter crash before success;
- task touched two or more packages;
- method evidence policy requires review;
- the run profile explicitly enables `review_mode: "strict"`.

Review is optional when task risk is low, claims are narrow, verification
passed, no recovery happened, and the run profile uses the default review mode.

### 7.3 Review artifacts

Each review writes an artifact:

```ts
interface TaskReviewArtifact {
  schema: "waygent.task_review.v1";
  run_id: string;
  task_id: string;
  review_id: string;
  role: "spec_reviewer" | "quality_reviewer";
  status: "passed" | "failed" | "needs_fix";
  verdict: "approved" | "rejected";
  issues: Array<{
    severity: "critical" | "important" | "minor";
    file?: string;
    line?: number;
    summary: string;
    required_fix: string;
  }>;
  evidence_refs: string[];
  reviewed_patch_refs: string[];
  model?: string;
  created_at: string;
}
```

The state stores review refs under each task and under `state.reviews`.
Completion audit reads review artifacts, not free-form provider summaries.

### 7.4 Review state transitions

Per task, the target logical phase order is:

```text
verification_passed
  -> review_pending
  -> spec_review_running
  -> spec_review_failed | spec_review_passed
  -> quality_review_running
  -> quality_review_failed | review_passed
  -> checkpoint_ready
```

The existing persisted task status may still use `verified` for backward
compatibility. New review fields disambiguate whether that task is also
review-passed and checkpoint-ready.

If a review fails:

- runtime schedules repair when patch evidence exists;
- repair packet includes review issues and prior diff;
- successful repair invalidates prior failed review and schedules re-review;
- exhaustion becomes `review_failed`, not `verification_failed`.

### 7.5 Review command

Add CLI commands:

```bash
waygent review --run <id>
waygent review --run <id> --task <task_id>
waygent review --run <id> --role spec_reviewer
waygent review --run <id> --role quality_reviewer
```

Automatic review dispatch uses the same implementation path as the manual
command. Manual review does not bypass budgets or apply readiness.

## 8. P2 - Cost and Adapter Hygiene

### 8.1 Repair-first recovery

Existing repair worker work remains the foundation. P2 tightens the decision
tree:

| Failure class | Default action |
|---|---|
| `verification_failed` with patch evidence | `dispatch_repair` |
| `review_failed` with patch evidence | `dispatch_repair` |
| `diff_scope_failed` with patch evidence | `dispatch_repair_scope_lock` |
| `malformed_result` with salvageable patch | `salvage_patch_then_review` |
| `adapter_crashed` with salvageable patch | `salvage_patch_then_review` |
| `environment_blocker` | `request_decision` |
| `dependency_missing` | `request_decision` |
| `command_not_found` | `request_decision` |
| `timeout` with partial patch | `salvage_patch_then_review` |
| `timeout` without patch | `retry_with_budget_check` |

Full implementer retry is used only when repair/salvage is not possible.

### 8.2 Salvage-first adapter handling

Provider adapters already record stdout, stderr, worker result refs, and patch
refs. P2 formalizes crash salvage:

```ts
interface SalvageResult {
  schema: "waygent.salvage_result.v1";
  task_id: string;
  attempt_id: string;
  status: "salvaged_patch" | "no_patch" | "unsafe_patch";
  patch_ref: string | null;
  changed_files: string[];
  reason: string | null;
  evidence_refs: string[];
}
```

If patch salvage succeeds:

- runtime does not call it a completed implementation;
- runtime records `runway.patch_salvaged`;
- runtime verifies and reviews the patch before checkpointing;
- explain reports "salvaged patch requires review" rather than "adapter
  crashed."

### 8.3 Budget policy

Add run-level policy:

```yaml
budget:
  max_cost_usd: 50
  max_provider_minutes: 45
  max_full_worker_retries_per_task: 1
  max_repair_retries_per_task: 2
  action: pause_for_operator
```

Defaults:

- no hard cost cap unless requested;
- warning at `$50`, `$100`, `$250`, and `$500`;
- full worker retry cap of 1 after a successful patch exists;
- repair retry cap of 2;
- adapter crash retry cap of 1 before salvage/decision.

Events:

- `platform.budget_warning`
- `platform.budget_paused`
- `platform.cost_accumulated`

Operator surfaces show projected remaining budget and the reason the runtime
chose repair, retry, pause, or decision.

### 8.4 Stale running and orphan cleanup

Waygent adds stale-run classification:

```ts
interface StaleRunStatus {
  run_id: string;
  stale: boolean;
  reason:
    | "heartbeat_expired"
    | "provider_process_missing"
    | "worktree_missing"
    | "state_event_mismatch"
    | "manual_pause"
    | "active";
  safe_actions: Array<"inspect" | "mark_blocked" | "resume" | "cleanup_worktree">;
}
```

Commands:

```bash
waygent orphans
waygent orphans --stale
waygent orphans --mark-blocked <run_id>
waygent orphans --cleanup-worktree <run_id>
```

Cleanup never deletes source checkout files, committed branches, or artifacts
needed by the state/event journal. It can remove abandoned temporary worktrees
only after the state records a terminal blocked/paused outcome.

## 9. Operator Surface

### 9.1 CLI explain

`waygent explain` shows:

- primary blocker;
- precise apply readiness reason;
- current required next action;
- recovered failures;
- review obligation status;
- cost summary;
- safe commands.

Example:

```json
{
  "blocked_by": "review_evidence_missing",
  "summary": "Run has verified checkpoints but recovery made review evidence mandatory.",
  "recovered_failures": [
    {
      "task_id": "phase_3_backend_service_web",
      "failure_class": "malformed_result",
      "recovered_by": "retry_with_strict_prompt"
    }
  ],
  "allowed_actions": [
    "waygent review --run readmates_admin_vnext_s2_platform_ops_health_20260525_162107",
    "waygent inspect --run readmates_admin_vnext_s2_platform_ops_health_20260525_162107"
  ]
}
```

### 9.2 Console and API

Console/API expose the same model:

- `status_summary.display_status`
- `primary_blocker.code`
- `apply_readiness.reason`
- `review_status`
- `recovered_failures`
- `cost_summary`
- `stale_run_status`

The console should not show `verification_failed` when all latest verification
records passed. It should show "Review required after recovery" with the
specific task and action.

## 10. Data Contracts

All schema changes are additive.

### 10.1 New event types

- `runway.verification_resolved`
- `runway.review_dispatched`
- `runway.review_result`
- `runway.review_failed`
- `runway.review_passed`
- `runway.patch_salvaged`
- `platform.budget_warning`
- `platform.budget_paused`
- `platform.stale_run_detected`
- `platform.orphan_cleanup_completed`

### 10.2 State additions

```ts
interface WaygentRunStateTaskV2 {
  review_refs?: string[];
  review_status?:
    | "not_required"
    | "required"
    | "pending"
    | "running"
    | "passed"
    | "failed";
  verification_resolution?: TaskVerificationResolution;
}

interface WaygentRunStateV2 {
  recovered_failures?: Array<{
    task_id: string;
    failure_class: string;
    recovered_at: string;
    evidence_refs: string[];
  }>;
  budget_policy?: Record<string, unknown>;
  stale_run_status?: StaleRunStatus;
}
```

### 10.3 Operator decision additions

```ts
interface OperatorDecision {
  review_status?: {
    required: boolean;
    missing_task_ids: string[];
    passed_task_ids: string[];
  };
  recovered_failures?: Array<{
    task_id: string;
    failure_class: string;
    evidence_refs: string[];
  }>;
  cost_summary?: {
    cost_usd: number;
    dispatches: number;
    budget_status: "ok" | "warning" | "paused" | "exhausted";
  };
}
```

## 11. Testing Plan

### 11.1 Unit tests

- `packages/lens-projectors/tests/operatorDecision.test.ts`
  - stale failed verification followed by pass is not primary blocker;
  - recovered malformed result with missing review shows
    `review_evidence_missing`;
  - terminal invariant blockers map to precise apply reasons.
- `packages/lens-projectors/tests/trust.test.ts`
  - recovered failures do not force `trust_status: "failed"`;
  - missing review yields `needs_review`;
  - active latest failure still yields `failed`.
- `packages/orchestrator/tests/reviewEvidence.test.ts`
  - recovery makes review required;
  - review artifacts satisfy the policy;
  - failed review schedules repair when patch evidence exists.
- `packages/orchestrator/tests/runCommandsV2.test.ts`
  - `review --run` writes review events and artifacts;
  - `apply` blocks with `review_evidence_missing` before review;
  - `apply` becomes ready after review passes.
- `packages/orchestrator/tests/recoveryExecutor.test.ts`
  - repair-first decisions for verification and review failures;
  - salvage decisions for adapter crash/malformed output with patch evidence;
  - budget pause decisions.

### 11.2 Integration tests

- `tests/integration/waygent-scenarios.test.ts`
  - add recovered verification fixture;
  - add missing-review fixture;
  - add review-pass apply-ready fixture;
  - add budget-paused fixture.
- `tests/integration/waygent-fixture-lab.test.ts`
  - include stale verification and recovered malformed output cases.
- `tests/integration/waygent-dogfood-evidence.test.ts`
  - assert explain/API/console projection agree on primary blocker and action.

### 11.3 Verification commands

Implementation should use the smallest relevant gate per slice. Full local gate
for the combined rollout:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:fixture-lab
bun run waygent:dogfood
bun run --cwd apps/console build
git diff --check
```

If native kernel code changes, add:

```bash
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

## 12. Rollout Plan

### Milestone P0

Land projection and explanation fixes first:

1. task verification resolver;
2. apply readiness reason taxonomy;
3. trust projection with recovered failure support;
4. CLI/API/console consistency tests.

P0 is complete when the inspected ReadMates pattern would explain as
`review_evidence_missing`, not `verification_failed`.

### Milestone P1

Land review lifecycle:

1. role routing for spec and quality reviewers;
2. review artifact schema and state refs;
3. automatic review dispatch for recovery-required tasks;
4. `waygent review` CLI;
5. completion audit consumes review artifacts.

P1 is complete when a recovered task can move from verified checkpoint to
review-passed to apply-ready without manual state edits.

### Milestone P2

Land cost and adapter hygiene:

1. repair-first recovery policy;
2. salvage result artifact;
3. cost budget policy and events;
4. stale run and orphan cleanup commands;
5. console/API cost and stale-run display.

P2 is complete when expensive full retries are avoided for scoped verification
failures and stale `running` runs have safe operator cleanup actions.

## 13. Risks

- **Projection overcorrection**: old failures must not disappear. They should
  move to recovered evidence, not be dropped.
- **Review cost creep**: mandatory review improves quality but can increase
  provider usage. Review role defaults should be cheaper than implementers
  unless the profile says otherwise.
- **State migration complexity**: older run states lack review fields. All
  readers must tolerate missing fields.
- **Operator confusion during rollout**: P0 may improve explain output before
  P1 can auto-run reviews. During that window, the action should be explicit:
  run review or inspect raw evidence.
- **False apply readiness**: the design must preserve Waygent's conservative
  apply authority. Precise blocker reasons should not loosen checkpoint,
  review, or dry-run requirements.

## 14. Acceptance Criteria

- A run with historical failed verification and later successful verification
  does not show `verification_failed` as the primary blocker.
- A run with successful recovery but missing required review shows
  `review_evidence_missing`.
- `waygent explain`, API detail, console UI model, and Lens operator decision
  agree on the primary blocker.
- Recovered failures remain visible as evidence and do not erase audit history.
- Review artifacts can satisfy completion audit.
- Repair worker is preferred over full worker retry when prior patch evidence
  exists.
- Adapter crash and malformed output with salvageable patch create salvage
  artifacts and route to review/repair rather than discard useful work.
- Budget warnings and pauses are emitted before runaway provider cost.
- Stale `running` runs can be inspected and marked blocked without mutating the
  source checkout.
- The full rollout passes:
  - `bun run check`
  - `bun run platform:demo`
  - `bun run waygent:scenarios`
  - `bun run waygent:fixture-lab`
  - `bun run waygent:dogfood`
  - `bun run --cwd apps/console build`
  - `git diff --check`
