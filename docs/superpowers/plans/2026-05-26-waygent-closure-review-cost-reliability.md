# Waygent Closure, Review, and Cost Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Waygent close runs with accurate blockers, automatic review evidence, repair-first recovery, cost controls, and safe stale-run cleanup.

**Architecture:** Implement this as three connected but independently testable slices. P0 fixes Lens/runtime projections so stale failures do not mask current state. P1 adds first-class review artifacts and lifecycle support. P2 extends recovery, budget, and orphan handling so expensive or stale runs become explicit operator states instead of ambiguous blockers.

**Tech Stack:** TypeScript, Bun test, `@waygent/contracts`, `@waygent/lens-projectors`, `@waygent/orchestrator`, `apps/cli`, `apps/api`, `apps/console`, JSONL event journals, filesystem run artifacts.

---

## Source Spec

- Design spec: `docs/superpowers/specs/2026-05-26-waygent-closure-review-cost-reliability-design.md`
- Current runtime entry points:
  - `packages/contracts/src/types.ts`
  - `packages/contracts/src/schemas.ts`
  - `packages/lens-projectors/src/apply.ts`
  - `packages/lens-projectors/src/trust.ts`
  - `packages/lens-projectors/src/operatorDecision.ts`
  - `packages/lens-projectors/src/runReadModel.ts`
  - `packages/orchestrator/src/completionAudit.ts`
  - `packages/orchestrator/src/reviewEvidence.ts`
  - `packages/orchestrator/src/recoveryExecutor.ts`
  - `packages/orchestrator/src/runCommands.ts`
  - `packages/orchestrator/src/orchestrator.ts`
  - `packages/orchestrator/src/orphanRuns.ts`
  - `packages/orchestrator/src/executionProfile.ts`
  - `apps/cli/src/index.ts`
  - `apps/api/src/server.ts`
  - `apps/console/src/uiModel.ts`

## File Structure Map

### Contracts

- Modify `packages/contracts/src/types.ts`
  - Add precise apply readiness reasons, task verification resolution, recovered failure records, review status records, stale run status records, salvage result, and budget policy types.
  - Extend `ProviderRole`, `ProviderCapabilityManifest.supported_modes`, `OperatorActionId`, `OperatorDecisionProjection`, `WaygentRunStateTaskV2`, `WaygentRunStateV2`, `TrustStatus`, and `LensRunwayProjection`.
- Modify `packages/contracts/src/schemas.ts`
  - Mirror the additive types above in JSON schemas.
- Modify `packages/contracts/tests/contracts.test.ts`
  - Validate new review, stale-run, salvage, trust, and operator decision examples.

### Lens Projectors

- Create `packages/lens-projectors/src/verificationResolution.ts`
  - Resolve latest task verification state from state records plus event journal.
- Create `packages/lens-projectors/src/applyReason.ts`
  - Map completion audit, terminal invariant, drift, and checkpoint conditions to precise apply readiness reasons.
- Modify `packages/lens-projectors/src/apply.ts`
  - Use `applyReason.ts` and expose precise readiness reasons.
- Modify `packages/lens-projectors/src/trust.ts`
  - Separate active and recovered failures and add `needs_review`.
- Modify `packages/lens-projectors/src/operatorDecision.ts`
  - Use verification resolution, review status, cost summary, recovered failures, and new action ids.
- Modify `packages/lens-projectors/src/runReadModel.ts`
  - Carry new trust/operator fields into read models.
- Modify `packages/lens-projectors/src/index.ts`
  - Export new helpers for orchestrator/API tests.
- Modify tests under `packages/lens-projectors/tests/`.

### Orchestrator

- Create `packages/orchestrator/src/reviewArtifacts.ts`
  - Write and read `waygent.task_review.v1` artifacts.
- Create `packages/orchestrator/src/reviewPacket.ts`
  - Build bounded spec/quality review packets.
- Create `packages/orchestrator/src/reviewRunner.ts`
  - Execute review roles through existing provider adapter plumbing or the fake provider in tests.
- Create `packages/orchestrator/src/salvage.ts`
  - Classify salvageable patches after adapter crash, malformed output, timeout, and diff scope failures.
- Create `packages/orchestrator/src/budgetPolicy.ts`
  - Resolve run-level cost policy and warning/pause thresholds.
- Modify `packages/orchestrator/src/reviewEvidence.ts`
  - Return missing task ids and support review artifacts.
- Modify `packages/orchestrator/src/completionAudit.ts`
  - Require review artifacts only when review policy says they are required, and explain why.
- Modify `packages/orchestrator/src/recoveryExecutor.ts`
  - Prefer repair/salvage decisions before full worker retry.
- Modify `packages/orchestrator/src/runCommands.ts`
  - Add `reviewRun`, improved `repairRun` blockers, budget-aware `costRun`, and stale orphan actions.
- Modify `packages/orchestrator/src/orchestrator.ts`
  - Schedule review phases after verification/recovery and before checkpoint-ready completion.
- Modify `packages/orchestrator/src/orphanRuns.ts`
  - Add stale-run classification and mark-blocked/cleanup-worktree safe actions.
- Modify tests under `packages/orchestrator/tests/`.

### CLI, API, Console

- Modify `apps/cli/src/index.ts`
  - Add `waygent review`, extend role flags, extend `waygent orphans`.
- Modify `apps/cli/tests/`.
- Modify `apps/api/src/server.ts` and `apps/api/tests/api.test.ts`
  - Return review status, recovered failures, cost summary, and stale-run status.
- Modify `apps/console/src/uiModel.ts`, `apps/console/src/App.tsx`, and tests.
  - Show precise blockers and review/cost/stale-run state.

### Integration Fixtures

- Modify `tests/integration/waygent-scenarios.test.ts`
- Modify `tests/integration/waygent-fixture-lab.test.ts`
- Modify `tests/integration/waygent-dogfood-evidence.test.ts`
- Add scenario fixtures under `tests/waygent-scenarios/`:
  - `stale-verification-recovered.json`
  - `missing-review-evidence.json`
  - `review-pass-apply-ready.json`
  - `budget-paused.json`
  - `salvaged-patch-needs-review.json`

---

### Task 1: Contracts for Closure, Review, Cost, and Stale Runs

```yaml waygent-task
id: task_1_contracts_closure_review_cost
title: Contracts for closure, review, cost, and stale runs
dependencies: []
file_claims:
  - path: packages/contracts/src/types.ts
    mode: owned
  - path: packages/contracts/src/schemas.ts
    mode: owned
  - path: packages/contracts/tests/contracts.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/contracts/tests/contracts.test.ts
```

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Test: `packages/contracts/tests/contracts.test.ts`

- [ ] **Step 1: Add failing contract tests**

Add tests for the new additive contracts in `packages/contracts/tests/contracts.test.ts`:

```ts
test("validates task review artifacts", () => {
  expect(validateContract("waygent.task_review.v1", {
    schema: "waygent.task_review.v1",
    run_id: "run_review",
    task_id: "task_a",
    review_id: "review_task_a_spec_1",
    role: "spec_reviewer",
    status: "passed",
    verdict: "approved",
    issues: [],
    evidence_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
    reviewed_patch_refs: ["artifacts/checkpoints/task_a/candidate_task_a.patch"],
    created_at: "2026-05-26T00:00:00.000Z"
  }).valid).toBe(true);
});

test("validates operator decision review and cost additions", () => {
  const decision = validOperatorDecisionFixture({
    review_status: {
      required: true,
      missing_task_ids: ["task_a"],
      passed_task_ids: []
    },
    recovered_failures: [{
      task_id: "task_a",
      failure_class: "malformed_result",
      evidence_refs: ["event:event_run_3"]
    }],
    cost_summary: {
      cost_usd: 57.25,
      dispatches: 4,
      budget_status: "warning"
    }
  });

  expect(validateContract("waygent.operator_decision.v1", decision).valid).toBe(true);
});

test("validates stale run status and salvage result", () => {
  expect(validateContract("waygent.salvage_result.v1", {
    schema: "waygent.salvage_result.v1",
    task_id: "task_a",
    attempt_id: "attempt_task_a_1",
    status: "salvaged_patch",
    patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
    changed_files: ["packages/orchestrator/src/example.ts"],
    reason: null,
    evidence_refs: ["artifacts/provider/attempt_task_a_1.stderr.txt"]
  }).valid).toBe(true);
});
```

If `validOperatorDecisionFixture` does not exist, define it in the same test file near the existing operator decision fixtures:

```ts
function validOperatorDecisionFixture(overrides: Record<string, unknown> = {}) {
  return {
    schema: "waygent.operator_decision.v1",
    run_id: "run_review",
    generated_at: "2026-05-26T00:00:00.000Z",
    status_summary: {
      display_status: "blocked",
      runtime_status: "blocked",
      lifecycle_outcome: "blocked",
      current_phase: "complete",
      active_tasks: 0,
      completed_tasks: 1,
      blocked_tasks: 0,
      apply_status: "blocked",
      summary: "run_review is blocked by review_evidence_missing."
    },
    primary_blocker: null,
    secondary_blockers: [],
    allowed_actions: [],
    blocked_actions: [],
    evidence_packet: {
      state_refs: ["state:/tmp/run/state.json"],
      event_refs: [],
      artifact_refs: [],
      verification_refs: [],
      checkpoint_refs: [],
      projection_refs: [],
      missing_refs: [],
      redaction_notes: []
    },
    ai_handoff: {
      purpose: "draft_repair_plan",
      prompt_summary: "Draft a repair plan from bounded evidence.",
      run_id: "run_review",
      current_status: "blocked",
      primary_blocker: null,
      secondary_blockers: [],
      allowed_action_ids: [],
      blocked_action_ids: [],
      constraints: ["Do not apply patches."],
      evidence_refs: ["state:/tmp/run/state.json"],
      missing_evidence: [],
      raw_fallback_refs: ["state:/tmp/run/state.json"],
      safety_notes: ["Waygent runtime remains apply authority."]
    },
    confidence: "deterministic",
    unknown_reasons: [],
    source_projection_refs: {
      run_state_v2: "state:/tmp/run/state.json",
      apply_readiness: "waygent.apply_readiness",
      execution_explanation: "waygent.execution_explanation.v1",
      operational_maturity: "waygent.operational_maturity.v1"
    },
    ...overrides
  };
}
```

- [ ] **Step 2: Run the contract tests and confirm failure**

Run: `bun test packages/contracts/tests/contracts.test.ts`

Expected: FAIL because schemas do not yet include `waygent.task_review.v1`, `waygent.salvage_result.v1`, or the new operator decision fields.

- [ ] **Step 3: Add additive contract types**

Modify `packages/contracts/src/types.ts`:

```ts
export type ProviderRole =
  | "implement"
  | "review"
  | "spec_reviewer"
  | "quality_reviewer"
  | "repair"
  | "fix"
  | "verify_assist";

export type ApplyReadinessReason =
  | "review_evidence_missing"
  | "completion_audit_failed"
  | "terminal_invariant_failed"
  | "state_reconciliation_failed"
  | "combined_apply_evidence_missing"
  | "combined_apply_patch_missing"
  | "checkpoint_not_apply_ready"
  | "state_drift"
  | "missing_apply_ready_evidence";

export interface TaskVerificationResolution {
  task_id: string;
  latest_status: "passed" | "failed" | "missing";
  latest_verification_ref: string | null;
  stale_failure_refs: string[];
}

export interface RecoveredFailureRecord {
  task_id: string;
  failure_class: FailureClass | string;
  recovered_at: string;
  evidence_refs: string[];
}

export type TaskReviewStatus = "not_required" | "required" | "pending" | "running" | "passed" | "failed";

export interface TaskReviewArtifact {
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

export interface SalvageResult {
  schema: "waygent.salvage_result.v1";
  task_id: string;
  attempt_id: string;
  status: "salvaged_patch" | "no_patch" | "unsafe_patch";
  patch_ref: string | null;
  changed_files: string[];
  reason: string | null;
  evidence_refs: string[];
}

export interface StaleRunStatus {
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

export interface CostSummaryProjection {
  cost_usd: number;
  dispatches: number;
  budget_status: "ok" | "warning" | "paused" | "exhausted";
}
```

Extend existing interfaces:

```ts
export type TrustStatus = "trusted" | "failed" | "insufficient_evidence" | "needs_review";

export type OperatorActionId =
  | "inspect_run"
  | "explain_run"
  | "open_raw_evidence"
  | "open_ai_repair_handoff"
  | "request_user_input"
  | "approve_recovery"
  | "resume_run"
  | "regenerate_checkpoint"
  | "rebase_checkpoint"
  | "rerun_verification"
  | "review_patch"
  | "run_review"
  | "mark_stale_blocked"
  | "cleanup_stale_worktree"
  | "apply_run";

export interface WaygentRunStateTaskV2 {
  review_refs?: string[];
  review_status?: TaskReviewStatus;
  verification_resolution?: TaskVerificationResolution;
}

export interface WaygentRunStateV2 {
  recovered_failures?: RecoveredFailureRecord[];
  stale_run_status?: StaleRunStatus;
}

export interface OperatorDecisionProjection {
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
  cost_summary?: CostSummaryProjection;
}
```

- [ ] **Step 4: Mirror the types in JSON schemas**

Modify `packages/contracts/src/schemas.ts`:

AJV compatibility rule: every schema property that uses `nullable` must also
declare an explicit `type`, and every string discriminator that uses `const`
must declare `type: "string"` alongside the `const`. Do not emit
`{ nullable: true }` or `{ const: "..." }` by itself.
For optional TypeScript fields such as `stale_run_status?: StaleRunStatus`,
make the property optional by omitting it from `required`; do not add
`nullable: true`. If null support is intentionally needed, use
`type: ["object", "null"]` or `anyOf`, never a bare `nullable`.

```ts
const providerRoleValues = [
  "implement",
  "review",
  "spec_reviewer",
  "quality_reviewer",
  "repair",
  "fix",
  "verify_assist"
] as const;

const trustStatusValues = ["trusted", "failed", "insufficient_evidence", "needs_review"] as const;

export const taskReviewArtifactSchema = {
  type: "object",
  required: [
    "schema",
    "run_id",
    "task_id",
    "review_id",
    "role",
    "status",
    "verdict",
    "issues",
    "evidence_refs",
    "reviewed_patch_refs",
    "created_at"
  ],
  properties: {
    schema: { type: "string", const: "waygent.task_review.v1" },
    run_id: { type: "string", minLength: 1 },
    task_id: { type: "string", minLength: 1 },
    review_id: { type: "string", minLength: 1 },
    role: { enum: ["spec_reviewer", "quality_reviewer"] },
    status: { enum: ["passed", "failed", "needs_fix"] },
    verdict: { enum: ["approved", "rejected"] },
    issues: {
      type: "array",
      items: {
        type: "object",
        required: ["severity", "summary", "required_fix"],
        properties: {
          severity: { enum: ["critical", "important", "minor"] },
          file: { type: "string" },
          line: { type: "number" },
          summary: { type: "string", minLength: 1 },
          required_fix: { type: "string", minLength: 1 }
        },
        additionalProperties: false
      }
    },
    evidence_refs: { type: "array", items: { type: "string" } },
    reviewed_patch_refs: { type: "array", items: { type: "string" } },
    model: { type: "string" },
    created_at: { type: "string", minLength: 1 }
  },
  additionalProperties: false
} as const;

export const salvageResultSchema = {
  type: "object",
  required: ["schema", "task_id", "attempt_id", "status", "patch_ref", "changed_files", "reason", "evidence_refs"],
  properties: {
    schema: { type: "string", const: "waygent.salvage_result.v1" },
    task_id: { type: "string", minLength: 1 },
    attempt_id: { type: "string", minLength: 1 },
    status: { enum: ["salvaged_patch", "no_patch", "unsafe_patch"] },
    patch_ref: { type: ["string", "null"] },
    changed_files: { type: "array", items: { type: "string" } },
    reason: { type: ["string", "null"] },
    evidence_refs: { type: "array", items: { type: "string" } }
  },
  additionalProperties: false
} as const;

export const staleRunStatusSchema = {
  type: "object",
  required: ["run_id", "stale", "reason", "safe_actions"],
  properties: {
    run_id: { type: "string", minLength: 1 },
    stale: { type: "boolean" },
    reason: {
      enum: [
        "heartbeat_expired",
        "provider_process_missing",
        "worktree_missing",
        "state_event_mismatch",
        "manual_pause",
        "active"
      ]
    },
    safe_actions: {
      type: "array",
      items: {
        enum: ["inspect", "mark_blocked", "resume", "cleanup_worktree"]
      }
    }
  },
  additionalProperties: false
} as const;
```

Add both schemas to the export map:

```ts
export const schemas = {
  ...existingSchemas,
  "waygent.task_review.v1": taskReviewArtifactSchema,
  "waygent.salvage_result.v1": salvageResultSchema
};
```

Preserve the current schema export style if the file uses an object literal instead of `existingSchemas`.

- [ ] **Step 5: Run contract tests**

Run: `bun test packages/contracts/tests/contracts.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/contracts/tests/contracts.test.ts
git commit -m "feat(contracts): add Waygent closure review cost contracts"
```

---

### Task 2: Verification Resolution and Precise Apply Readiness

```yaml waygent-task
id: task_2_verification_resolution_apply_readiness
title: Verification resolution and precise apply readiness
dependencies:
  - task_1_contracts_closure_review_cost
file_claims:
  - path: packages/lens-projectors/src/verificationResolution.ts
    mode: owned
  - path: packages/lens-projectors/src/applyReason.ts
    mode: owned
  - path: packages/lens-projectors/src/apply.ts
    mode: owned
  - path: packages/lens-projectors/src/operatorDecision.ts
    mode: owned
  - path: packages/lens-projectors/src/index.ts
    mode: owned
  - path: packages/lens-projectors/tests/operatorDecision.test.ts
    mode: owned
  - path: packages/lens-projectors/tests/apply.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/lens-projectors/tests/operatorDecision.test.ts packages/lens-projectors/tests/apply.test.ts
```

**Files:**
- Create: `packages/lens-projectors/src/verificationResolution.ts`
- Create: `packages/lens-projectors/src/applyReason.ts`
- Modify: `packages/lens-projectors/src/apply.ts`
- Modify: `packages/lens-projectors/src/operatorDecision.ts`
- Modify: `packages/lens-projectors/src/index.ts`
- Test: `packages/lens-projectors/tests/operatorDecision.test.ts`
- Test: `packages/lens-projectors/tests/apply.test.ts`

- [ ] **Step 1: Add failing operator decision test for stale verification**

Append to `packages/lens-projectors/tests/operatorDecision.test.ts`:

```ts
test("does not report stale failed verification after later pass", () => {
  const state = makeState({
    status: "blocked",
    lifecycle_outcome: "blocked",
    current_phase: "complete",
    tasks: {
      task_a: task("task_a", {
        status: "verified",
        latest_failure_class: null,
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"]
      })
    },
    verification: [
      {
        verification_id: "verify_task_a_1",
        task_id: "task_a",
        command: "bun test",
        status: "failed",
        verified_at: "2026-05-26T00:00:00.000Z"
      },
      {
        verification_id: "verify_task_a_2",
        task_id: "task_a",
        command: "bun test",
        status: "passed",
        verified_at: "2026-05-26T00:01:00.000Z"
      }
    ],
    completion_audit: {
      status: "failed",
      combined_apply_evidence: {
        status: "passed",
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        patch_ref: "artifacts/checkpoints/apply/run_demo.patch"
      },
      residual_risk: ["review_evidence:recovery_attempted"]
    },
    recovery: [{ task_id: "task_a", failure_class: "malformed_result" }],
    apply: { status: "blocked", reason: "missing_apply_ready_evidence" }
  });

  const projection = projectOperatorDecisionFromState({
    state,
    events: [
      demoEvent({
        event_id: "event_failed",
        sequence: 1,
        event_type: "runway.verification_result",
        outcome: "failed",
        payload: { task_id: "task_a", verification_id: "verify_task_a_1" }
      }),
      demoEvent({
        event_id: "event_passed",
        sequence: 2,
        event_type: "runway.verification_result",
        outcome: "success",
        payload: { task_id: "task_a", verification_id: "verify_task_a_2" }
      })
    ]
  });

  expect(projection.primary_blocker?.code).toBe("review_evidence_missing");
  expect(projection.primary_blocker?.code).not.toBe("verification_failed");
  expect(projection.recovered_failures).toContainEqual(expect.objectContaining({
    task_id: "task_a",
    failure_class: "malformed_result"
  }));
});
```

- [ ] **Step 2: Add failing apply readiness taxonomy test**

Append to `packages/lens-projectors/tests/apply.test.ts`:

```ts
test("maps review residual risk to review_evidence_missing", () => {
  const state = stateFixture({
    apply: { status: "blocked", reason: "missing_apply_ready_evidence" },
    completion_audit: {
      status: "failed",
      combined_apply_evidence: {
        status: "passed",
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        patch_ref: "artifacts/checkpoints/apply/run_demo.patch"
      },
      residual_risk: ["review_evidence:recovery_attempted"]
    },
    tasks: {
      task_a: {
        status: "verified",
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        latest_failure_class: null
      }
    }
  });

  expect(projectApplyReadinessFromState(state)).toMatchObject({
    status: "blocked",
    reason: "review_evidence_missing",
    checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
    combined_patch_ref: "artifacts/checkpoints/apply/run_demo.patch"
  });
});
```

- [ ] **Step 3: Run tests and confirm failure**

Run: `bun test packages/lens-projectors/tests/operatorDecision.test.ts packages/lens-projectors/tests/apply.test.ts`

Expected: FAIL because stale verification and review residual risk are not resolved.

- [ ] **Step 4: Implement verification resolver**

Create `packages/lens-projectors/src/verificationResolution.ts`:

```ts
import type { AgentLensEvent, TaskVerificationResolution, WaygentRunStateV2 } from "@waygent/contracts";

interface VerificationCandidate {
  task_id: string;
  status: "passed" | "failed";
  ref: string;
  order: number;
}

export function resolveTaskVerifications(state: WaygentRunStateV2, events: AgentLensEvent[]): Record<string, TaskVerificationResolution> {
  const byTask = new Map<string, VerificationCandidate[]>();
  for (const [index, record] of state.verification.entries()) {
    const taskId = typeof record.task_id === "string" ? record.task_id : null;
    if (!taskId) continue;
    const rawStatus = String(record.status ?? record.outcome ?? "");
    const status = rawStatus === "passed" || rawStatus === "success" ? "passed" : rawStatus === "failed" ? "failed" : null;
    if (!status) continue;
    const ref = typeof record.kernel_result_ref === "string"
      ? record.kernel_result_ref
      : typeof record.verification_id === "string"
        ? `verification_id:${record.verification_id}`
        : `verification_state:${index}`;
    const time = typeof record.verified_at === "string" ? Date.parse(record.verified_at) : Number.NaN;
    pushCandidate(byTask, { task_id: taskId, status, ref, order: Number.isFinite(time) ? time : index });
  }

  for (const event of events) {
    if (event.event_type !== "runway.verification_result") continue;
    const taskId = typeof event.payload.task_id === "string" ? event.payload.task_id : null;
    if (!taskId) continue;
    const status = event.outcome === "success" ? "passed" : event.outcome === "failed" ? "failed" : null;
    if (!status) continue;
    pushCandidate(byTask, {
      task_id: taskId,
      status,
      ref: `event:${event.event_id}`,
      order: event.sequence
    });
  }

  const out: Record<string, TaskVerificationResolution> = {};
  for (const task of Object.values(state.tasks)) {
    const candidates = [...(byTask.get(task.id) ?? [])].sort((left, right) => left.order - right.order);
    const latest = candidates.at(-1);
    const staleFailureRefs = candidates
      .slice(0, -1)
      .filter((candidate) => candidate.status === "failed")
      .map((candidate) => candidate.ref);
    out[task.id] = {
      task_id: task.id,
      latest_status: latest?.status ?? "missing",
      latest_verification_ref: latest?.ref ?? null,
      stale_failure_refs: staleFailureRefs
    };
  }
  return out;
}

function pushCandidate(map: Map<string, VerificationCandidate[]>, candidate: VerificationCandidate): void {
  const existing = map.get(candidate.task_id) ?? [];
  existing.push(candidate);
  map.set(candidate.task_id, existing);
}

export function hasActiveVerificationFailure(
  state: WaygentRunStateV2,
  events: AgentLensEvent[]
): { task_id: string; evidence_refs: string[] } | null {
  const resolutions = resolveTaskVerifications(state, events);
  for (const task of Object.values(state.tasks)) {
    const resolution = resolutions[task.id];
    if (!resolution) continue;
    if (resolution.latest_status === "failed") {
      return {
        task_id: task.id,
        evidence_refs: [resolution.latest_verification_ref].filter((ref): ref is string => typeof ref === "string")
      };
    }
  }
  return null;
}
```

- [ ] **Step 5: Implement apply reason mapper**

Create `packages/lens-projectors/src/applyReason.ts`:

```ts
import type { ApplyReadinessReason, WaygentRunStateV2 } from "@waygent/contracts";

export function applyReadinessReasonFromState(state: WaygentRunStateV2): ApplyReadinessReason {
  if (state.drift.unrepaired_blockers.length > 0) return "state_drift";
  const audit = state.completion_audit as {
    status?: string;
    residual_risk?: unknown;
    terminal_invariant?: { blockers?: Array<{ code?: string }> };
    state_reconciliation?: { passed?: boolean };
    combined_apply_evidence?: { status?: string; patch_ref?: string };
  } | null;

  if (!audit) return "missing_apply_ready_evidence";
  const residual = Array.isArray(audit.residual_risk) ? audit.residual_risk.map(String) : [];
  if (residual.some((item) => item.startsWith("review_evidence:"))) return "review_evidence_missing";
  if (audit.state_reconciliation && audit.state_reconciliation.passed === false) return "state_reconciliation_failed";
  if (Array.isArray(audit.terminal_invariant?.blockers) && audit.terminal_invariant.blockers.length > 0) {
    return "terminal_invariant_failed";
  }
  if (!audit.combined_apply_evidence) return "combined_apply_evidence_missing";
  if (audit.combined_apply_evidence.status !== "passed") return "checkpoint_not_apply_ready";
  if (!audit.combined_apply_evidence.patch_ref) return "combined_apply_patch_missing";
  if (audit.status !== "passed") return "completion_audit_failed";
  return "missing_apply_ready_evidence";
}
```

- [ ] **Step 6: Wire apply readiness**

Modify `packages/lens-projectors/src/apply.ts`:

```ts
import { applyReadinessReasonFromState } from "./applyReason";
```

Replace the final return in `projectApplyReadinessFromState` with:

```ts
  return {
    status: state.apply.status === "blocked" ? "blocked" : "not_ready",
    reason: applyReadinessReasonFromState(state),
    checkpoint_refs: refs,
    combined_patch_ref: patchRef,
    source: "run_state_v2"
  };
```

- [ ] **Step 7: Wire operator decision**

Modify `packages/lens-projectors/src/operatorDecision.ts`:

```ts
import { hasActiveVerificationFailure, resolveTaskVerifications } from "./verificationResolution";
```

Replace the verification blocker condition with:

```ts
  const activeVerificationFailure = hasActiveVerificationFailure(state, events);
  if (taskFailure?.failureClass === "verification_failed" || activeVerificationFailure) {
    const taskId = taskFailure?.task.id ?? activeVerificationFailure?.task_id ?? null;
    blockers.push(makeBlocker({
      code: "verification_failed",
      title: "Verification failed",
      summary: taskId ? `${taskId} failed verification.` : "Verification failed for the run.",
      severity: "blocking",
      taskId,
      evidenceRefs: verificationEvidenceRefs(taskId, events, evidencePacket),
      recommendedActionIds: ["rerun_verification", "open_ai_repair_handoff"]
    }));
  }
```

Add a new blocker before the generic `apply_blocked` fallback:

```ts
  if (applyReadiness.status === "blocked" && applyReadiness.reason === "review_evidence_missing") {
    blockers.push(makeBlocker({
      code: "review_evidence_missing",
      title: "Review evidence is missing",
      summary: "A recovered or high-risk task needs review evidence before apply.",
      severity: "blocking",
      evidenceRefs: evidencePacket.state_refs,
      missingRefs: ["review_refs"],
      recommendedActionIds: ["run_review", "open_raw_evidence"]
    }));
  }
```

Add recovered failures to the returned projection:

```ts
    recovered_failures: recoveredFailuresFromState(state),
```

Define the helper near the other state-derived helpers:

```ts
function recoveredFailuresFromState(state: WaygentRunStateV2): NonNullable<OperatorDecisionProjection["recovered_failures"]> {
  return (state.recovered_failures ?? []).map((record) => ({
    task_id: record.task_id,
    failure_class: String(record.failure_class),
    evidence_refs: record.evidence_refs
  }));
}
```

- [ ] **Step 8: Export helpers**

Modify `packages/lens-projectors/src/index.ts`:

```ts
export * from "./verificationResolution";
export * from "./applyReason";
```

- [ ] **Step 9: Run tests**

Run: `bun test packages/lens-projectors/tests/operatorDecision.test.ts packages/lens-projectors/tests/apply.test.ts`

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add packages/lens-projectors/src packages/lens-projectors/tests
git commit -m "fix(lens): resolve stale verification and apply blockers"
```

---

### Task 3: Trust Projection and Read Model Consistency

```yaml waygent-task
id: task_3_trust_read_model_consistency
title: Trust projection and read model consistency
dependencies:
  - task_2_verification_resolution_apply_readiness
file_claims:
  - path: packages/lens-projectors/src/trust.ts
    mode: owned
  - path: packages/lens-projectors/src/runReadModel.ts
    mode: owned
  - path: packages/lens-projectors/tests/trust.test.ts
    mode: owned
  - path: packages/lens-projectors/tests/runReadModel.test.ts
    mode: owned
  - path: apps/api/src/server.ts
    mode: owned
  - path: apps/api/tests/api.test.ts
    mode: owned
  - path: apps/console/src/uiModel.ts
    mode: owned
  - path: apps/console/src/uiModel.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/lens-projectors/tests/trust.test.ts packages/lens-projectors/tests/runReadModel.test.ts apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts
```

**Files:**
- Modify: `packages/lens-projectors/src/trust.ts`
- Modify: `packages/lens-projectors/src/runReadModel.ts`
- Modify: `apps/api/src/server.ts`
- Modify: `apps/console/src/uiModel.ts`
- Test: `packages/lens-projectors/tests/trust.test.ts`
- Test: `packages/lens-projectors/tests/runReadModel.test.ts`
- Test: `apps/api/tests/api.test.ts`
- Test: `apps/console/src/uiModel.test.ts`

- [ ] **Step 1: Add failing trust tests**

Append to `packages/lens-projectors/tests/trust.test.ts`:

```ts
test("recovered failures do not force failed trust", () => {
  const events = [
    demoEvent({ event_id: "event_1", sequence: 1, event_type: "runway.verification_result", outcome: "failed" }),
    demoEvent({ event_id: "event_2", sequence: 2, event_type: "runway.recovery_scheduled", outcome: "success" }),
    demoEvent({ event_id: "event_3", sequence: 3, event_type: "runway.verification_result", outcome: "success" })
  ];

  expect(projectTrustReport(events, {
    active_failure_count: 0,
    recovered_failure_count: 1,
    review_required: false
  })).toMatchObject({
    trust_status: "trusted",
    active_failure_count: 0,
    recovered_failure_count: 1
  });
});

test("missing review yields needs_review trust", () => {
  expect(projectTrustReport([demoEvent({ outcome: "success" })], {
    active_failure_count: 0,
    recovered_failure_count: 1,
    review_required: true
  })).toMatchObject({
    trust_status: "needs_review",
    reasons: expect.arrayContaining(["review evidence required"])
  });
});
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `bun test packages/lens-projectors/tests/trust.test.ts`

Expected: FAIL because `projectTrustReport` does not accept resolution context and has no `needs_review` status.

- [ ] **Step 3: Implement resolved trust report**

Modify `packages/lens-projectors/src/trust.ts`:

```ts
export interface TrustResolutionInput {
  active_failure_count?: number;
  recovered_failure_count?: number;
  review_required?: boolean;
}

export interface TrustReport {
  trust_status: TrustStatus;
  total_events: number;
  evidence_score: number;
  active_failure_count: number;
  recovered_failure_count: number;
  reasons: string[];
}

export function projectTrustReport(events: AgentLensEvent[], resolution: TrustResolutionInput = {}): TrustReport {
  const verification = events.filter((event) => event.event_type.includes("verification") && event.outcome === "success");
  const kernel = events.filter((event) => event.event_type.startsWith("kernel.") && event.outcome === "success");
  const activeFailures = resolution.active_failure_count ?? events.filter((event) => event.outcome === "failed" || event.outcome === "blocked").length;
  const recoveredFailures = resolution.recovered_failure_count ?? 0;

  if (activeFailures > 0) {
    return {
      trust_status: "failed",
      total_events: events.length,
      evidence_score: -activeFailures,
      active_failure_count: activeFailures,
      recovered_failure_count: recoveredFailures,
      reasons: ["active failure evidence present"]
    };
  }
  if (resolution.review_required) {
    return {
      trust_status: "needs_review",
      total_events: events.length,
      evidence_score: verification.length * 2 + kernel.length,
      active_failure_count: 0,
      recovered_failure_count: recoveredFailures,
      reasons: ["review evidence required"]
    };
  }
  if (verification.length === 0 && kernel.length === 0) {
    return {
      trust_status: "insufficient_evidence",
      total_events: events.length,
      evidence_score: 0,
      active_failure_count: 0,
      recovered_failure_count: recoveredFailures,
      reasons: ["verification or kernel evidence required"]
    };
  }
  return {
    trust_status: "trusted",
    total_events: events.length,
    evidence_score: verification.length * 2 + kernel.length,
    active_failure_count: 0,
    recovered_failure_count: recoveredFailures,
    reasons: ["verification/kernel evidence outranks final agent claims"]
  };
}
```

Update `projectRunwayProjection` to treat `needs_review` as blocked:

```ts
const status: RunStatus = blocked || trust.trust_status === "needs_review"
  ? "blocked"
  : failed
    ? "failed"
    : trust.trust_status === "trusted"
      ? "completed"
      : "running";
```

Hard acceptance:

- `TrustReport.trust_status` must be typed as the shared `TrustStatus`, not as
  the previous narrow union of `"trusted" | "failed" | "insufficient_evidence"`.
- `projectTrustReport(...)` must be allowed to return `"needs_review"` without
  a TypeScript error.
- `projectRunwayProjection(...)` must accept `needs_review` as a valid trust
  projection and map it to a blocked run state before the trusted/completed
  branch.

- [ ] **Step 4: Carry fields through read model, API, and console**

Modify `packages/lens-projectors/src/runReadModel.ts` so the run read model exposes `trust.active_failure_count`, `trust.recovered_failure_count`, `operator_decision.recovered_failures`, `operator_decision.review_status`, and `operator_decision.cost_summary`.

Modify `apps/api/src/server.ts` detail response types and response builders:

```ts
review_status: model.operator_decision?.review_status ?? null,
recovered_failures: model.operator_decision?.recovered_failures ?? [],
cost_summary: model.operator_decision?.cost_summary ?? null,
```

Modify `apps/console/src/uiModel.ts`:

```ts
reviewStatus: detail.review_status ?? null,
recoveredFailures: detail.recovered_failures ?? [],
costSummary: detail.cost_summary ?? null,
```

- [ ] **Step 5: Add API and console tests**

Add assertions to existing API/console detail tests:

```ts
expect(body.review_status).toEqual({
  required: true,
  missing_task_ids: ["task_a"],
  passed_task_ids: []
});
expect(body.recovered_failures).toContainEqual(expect.objectContaining({
  task_id: "task_a",
  failure_class: "malformed_result"
}));
expect(body.cost_summary).toMatchObject({ budget_status: "warning" });
```

Console model assertion:

```ts
expect(model.runs[0]?.trust.reasons).toContain("trust status: needs_review");
expect(model.detail?.operator.recoveredFailures[0]?.taskId).toBe("task_a");
expect(model.detail?.operator.reviewStatus?.missingTaskIds).toEqual(["task_a"]);
```

- [ ] **Step 6: Run tests**

Run: `bun test packages/lens-projectors/tests/trust.test.ts packages/lens-projectors/tests/runReadModel.test.ts apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/lens-projectors/src packages/lens-projectors/tests apps/api/src apps/api/tests apps/console/src
git commit -m "feat(lens): expose recovered failures and review trust"
```

---

### Task 4: Review Evidence Policy and Completion Audit

```yaml waygent-task
id: task_4_review_evidence_completion_audit
title: Review evidence policy and completion audit
dependencies:
  - task_1_contracts_closure_review_cost
file_claims:
  - path: packages/orchestrator/src/reviewEvidence.ts
    mode: owned
  - path: packages/orchestrator/src/reviewArtifacts.ts
    mode: owned
  - path: packages/orchestrator/src/completionAudit.ts
    mode: owned
  - path: packages/orchestrator/src/index.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/tests/reviewEvidence.test.ts
    mode: owned
  - path: packages/orchestrator/tests/completionAudit.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/reviewEvidence.test.ts packages/orchestrator/tests/completionAudit.test.ts
```

**Files:**
- Create: `packages/orchestrator/src/reviewArtifacts.ts`
- Modify: `packages/orchestrator/src/reviewEvidence.ts`
- Modify: `packages/orchestrator/src/completionAudit.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Test: `packages/orchestrator/tests/reviewEvidence.test.ts`
- Test: `packages/orchestrator/tests/completionAudit.test.ts`

- [ ] **Step 1: Add failing review evidence tests**

Create or extend `packages/orchestrator/tests/reviewEvidence.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { reviewEvidenceMissing, reviewEvidencePolicy, requiredReviewTaskIds } from "../src/reviewEvidence";
import { baseV2State } from "./support/runStateFixture";

describe("review evidence policy", () => {
  test("recovery requires review evidence for the recovered task", () => {
    const state = baseV2State({ root: "/tmp/waygent", run_id: "run_review" });
    state.tasks.task_a.status = "verified";
    state.recovery = [{ task_id: "task_a", failure_class: "malformed_result" }];

    expect(reviewEvidencePolicy(state)).toEqual({
      required: true,
      reason: "recovery_attempted",
      missing_task_ids: ["task_a"],
      passed_task_ids: []
    });
    expect(reviewEvidenceMissing({ state, review_evidence: [] })).toBe("recovery_attempted");
  });

  test("passed review artifact satisfies recovery review requirement", () => {
    const state = baseV2State({ root: "/tmp/waygent", run_id: "run_review" });
    state.tasks.task_a.status = "verified";
    state.tasks.task_a.review_refs = ["artifacts/reviews/task_a/spec_review_1.json"];
    state.tasks.task_a.review_status = "passed";
    state.recovery = [{ task_id: "task_a", failure_class: "malformed_result" }];
    state.reviews = [{
      schema: "runway.review_result.v1",
      run_id: "run_review",
      task_id: "task_a",
      attempt_id: "review_task_a_1",
      provider: "fake",
      verdict: "pass",
      spec_score: 1,
      quality_score: 1,
      findings: [],
      residual_risk: [],
      summary: "Review passed."
    }];

    expect(requiredReviewTaskIds(state)).toEqual(["task_a"]);
    expect(reviewEvidenceMissing({ state, review_evidence: state.reviews })).toBe(null);
  });
});
```

- [ ] **Step 2: Add failing completion audit test**

Append to `packages/orchestrator/tests/completionAudit.test.ts`:

```ts
test("completion audit fails with a precise review evidence residual risk", () => {
  const state = baseV2State({ root: root, run_id: "run_review_audit" });
  state.tasks.task_a.status = "verified";
  state.tasks.task_a.checkpoint_refs = [writePassedCheckpoint(state, "task_a")];
  state.recovery = [{ task_id: "task_a", failure_class: "malformed_result" }];

  const audit = buildCompletionAudit({
    state,
    required_checks: ["git diff --check"],
    verification_evidence: [{ task_id: "task_a", status: "passed" }],
    review_evidence: [],
    combined_apply_evidence: createCombinedCheckpointPatchArtifact({
      run_root: state.run_root,
      run_id: state.run_id,
      checkpoint_refs: state.tasks.task_a.checkpoint_refs,
      source: state.workspace
    }),
    prompt_to_artifact_checklist: ["task_packet_written"]
  });

  expect(audit.status).toBe("failed");
  expect(audit.residual_risk).toContain("review_evidence:recovery_attempted");
});
```

- [ ] **Step 3: Run tests and confirm failure**

Run: `bun test packages/orchestrator/tests/reviewEvidence.test.ts packages/orchestrator/tests/completionAudit.test.ts`

Expected: FAIL because review policy returns only a boolean/reason and does not compute task ids or artifact satisfaction.

- [ ] **Step 4: Implement review artifacts helper**

Create `packages/orchestrator/src/reviewArtifacts.ts`:

```ts
import { readFileSync } from "node:fs";
import type { TaskReviewArtifact, WaygentRunStateV2 } from "@waygent/contracts";
import { resolveRunArtifactPath } from "./checkpointArtifacts";

export function readTaskReviewArtifact(state: WaygentRunStateV2, ref: string): TaskReviewArtifact | null {
  try {
    return JSON.parse(readFileSync(resolveRunArtifactPath(state.run_root, ref), "utf8")) as TaskReviewArtifact;
  } catch {
    return null;
  }
}

export function taskHasPassedReviewEvidence(state: WaygentRunStateV2, taskId: string): boolean {
  const task = state.tasks[taskId];
  if (!task) return false;
  if (task.review_status === "passed") return true;
  if (state.reviews.some((review) => review.task_id === taskId && review.verdict === "pass")) return true;
  return (task.review_refs ?? []).some((ref) => {
    const artifact = readTaskReviewArtifact(state, ref);
    return artifact?.status === "passed" && artifact.verdict === "approved";
  });
}
```

- [ ] **Step 5: Implement review evidence policy**

Modify `packages/orchestrator/src/reviewEvidence.ts`:

```ts
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { taskHasPassedReviewEvidence } from "./reviewArtifacts";

export interface ReviewEvidencePolicy {
  required: boolean;
  reason: string | null;
  missing_task_ids: string[];
  passed_task_ids: string[];
}

export function requiredReviewTaskIds(state: WaygentRunStateV2): string[] {
  const ids = new Set<string>();
  if (state.method_evidence_required) {
    for (const task of Object.values(state.tasks)) ids.add(task.id);
  }
  for (const task of Object.values(state.tasks)) {
    if (task.risk === "high") ids.add(task.id);
    if ((task.file_claims ?? []).some((claim) => claim.mode === "owned" && isBroadClaim(claim.path))) ids.add(task.id);
  }
  for (const recovery of state.recovery ?? []) {
    const taskId = typeof recovery.task_id === "string" ? recovery.task_id : null;
    if (taskId && state.tasks[taskId]) ids.add(taskId);
  }
  return [...ids].sort();
}

export function reviewEvidencePolicy(state: WaygentRunStateV2): ReviewEvidencePolicy {
  const requiredIds = requiredReviewTaskIds(state);
  const passed = requiredIds.filter((taskId) => taskHasPassedReviewEvidence(state, taskId));
  const missing = requiredIds.filter((taskId) => !passed.includes(taskId));
  const reason = state.method_evidence_required
    ? "method_evidence_required"
    : Object.values(state.tasks).some((task) => task.risk === "high")
      ? "high_risk_task"
      : (state.recovery ?? []).length > 0
        ? "recovery_attempted"
        : missing.length > 0
          ? "review_required"
          : null;
  return {
    required: requiredIds.length > 0,
    reason,
    missing_task_ids: missing,
    passed_task_ids: passed
  };
}

export function reviewEvidenceMissing(input: {
  state: WaygentRunStateV2;
  review_evidence: Array<Record<string, unknown>>;
}): string | null {
  const policy = reviewEvidencePolicy({ ...input.state, reviews: input.review_evidence as WaygentRunStateV2["reviews"] });
  if (!policy.required) return null;
  return policy.missing_task_ids.length > 0 ? policy.reason ?? "review_required" : null;
}

function isBroadClaim(path: string): boolean {
  return path === "." || path === "*" || (path.split("/").length <= 1 && path.endsWith("*"));
}
```

- [ ] **Step 6: Keep completion audit residual risk precise**

Modify `packages/orchestrator/src/completionAudit.ts` so the existing `reviewEvidenceMissing` call remains, but its result is emitted as:

```ts
if (missingReviewReason) {
  residualRisk.push(`review_evidence:${missingReviewReason}`);
}
```

This may already be present; keep the exact prefix because Task 2 maps it to `review_evidence_missing`.

- [ ] **Step 7: Run tests**

Run: `bun test packages/orchestrator/tests/reviewEvidence.test.ts packages/orchestrator/tests/completionAudit.test.ts`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/orchestrator/src/reviewEvidence.ts packages/orchestrator/src/reviewArtifacts.ts packages/orchestrator/src/completionAudit.ts packages/orchestrator/src/index.ts packages/orchestrator/tests/reviewEvidence.test.ts packages/orchestrator/tests/completionAudit.test.ts
git commit -m "feat(orchestrator): require review evidence after recovery"
```

---

### Task 5: Manual Review Command and Review Packet

```yaml waygent-task
id: task_5_review_command_packet
title: Manual review command and review packet
dependencies:
  - task_1_contracts_closure_review_cost
  - task_4_review_evidence_completion_audit
file_claims:
  - path: packages/orchestrator/src/reviewPacket.ts
    mode: owned
  - path: packages/orchestrator/src/reviewRunner.ts
    mode: owned
  - path: packages/orchestrator/src/runCommands.ts
    mode: owned
  - path: packages/orchestrator/src/index.ts
    mode: owned
  - path: packages/contracts/src/types.ts
    mode: owned
  - path: packages/contracts/src/schemas.ts
    mode: owned
  - path: apps/cli/src/index.ts
    mode: owned
  - path: apps/cli/tests/cli.test.ts
    mode: owned
  - path: packages/orchestrator/tests/reviewRun.test.ts
    mode: owned
risk: medium
verify:
  - bun test apps/cli/tests/cli.test.ts packages/orchestrator/tests/reviewRun.test.ts
```

**Files:**
- Create: `packages/orchestrator/src/reviewPacket.ts`
- Create: `packages/orchestrator/src/reviewRunner.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `apps/cli/src/index.ts`
- Test: `apps/cli/tests/cli.test.ts`
- Test: `packages/orchestrator/tests/reviewRun.test.ts`

- [ ] **Step 1: Add failing CLI test**

Append to `apps/cli/tests/cli.test.ts`:

```ts
test("parses review command flags", async () => {
  const parsed = parseCli(["review", "--run", "run_review", "--task", "task_a", "--role", "spec_reviewer", "--dry-run"]);
  expect(parsed).toEqual({
    command: "review",
    flags: {
      run: "run_review",
      task: "task_a",
      role: "spec_reviewer",
      "dry-run": true
    }
  });
});
```

- [ ] **Step 2: Add failing review command test**

Create `packages/orchestrator/tests/reviewRun.test.ts`:

```ts
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { reviewRun } from "../src/runCommands";
import { runStatePath, writeRunStateV2 } from "../src/runState";
import { baseV2State } from "./support/runStateFixture";

describe("reviewRun", () => {
  test("builds a dry-run review packet for a required task", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-review-run-"));
    const runId = "run_review";
    const state = baseV2State({ root, run_id: runId });
    const runRoot = join(root, runId);
    const worktree = join(root, "worktrees", runId, "task_a");
    mkdirSync(worktree, { recursive: true });
    writeFileSync(join(worktree, "a.txt"), "hello\n");
    state.run_root = runRoot;
    state.artifact_root = join(runRoot, "artifacts");
    state.state_path = runStatePath(root, runId);
    state.event_journal_path = join(runRoot, "events.jsonl");
    state.tasks.task_a.status = "verified";
    state.tasks.task_a.checkpoint_refs = ["artifacts/checkpoints/task_a/candidate_task_a.json"];
    state.tasks.task_a.review_status = "required";
    state.worktrees = [{
      task_id: "task_a",
      branch: "waygent/run_review/task_a",
      path: worktree,
      source: root,
      source_commit: null,
      cleanup_status: "active"
    }];
    state.recovery = [{ task_id: "task_a", failure_class: "malformed_result" }];
    writeRunStateV2(root, state);

    const result = await reviewRun({ root, run: runId, task: "task_a", role: "spec_reviewer", dry_run: true });

    expect(result).toMatchObject({
      command: "review",
      run_id: runId,
      task_id: "task_a",
      status: "dry_run",
      packet: {
        role: "spec_reviewer",
        task_id: "task_a"
      }
    });
  });
});
```

- [ ] **Step 3: Run tests and confirm failure**

Run: `bun test apps/cli/tests/cli.test.ts packages/orchestrator/tests/reviewRun.test.ts`

Expected: FAIL because `reviewRun` and CLI command wiring do not exist.

Hard acceptance for CLI blocked responses:

- `waygent review --run <missing> --role spec_reviewer` must preserve the
  requested role in its blocked response:
  `{ command: "review", run_id, role: "spec_reviewer", status: "blocked", reason: "missing_run_state_v2" }`.
- `reviewRun` may include additional diagnostic arrays such as `packet_refs`,
  `review_refs`, or `task_ids`, but those additions must not replace or omit
  the requested `role`.
- Apply the same role preservation to `no_reviewable_task` blocked responses.
- Keep the focused CLI assertion strict enough to catch a missing `role`; do
  not loosen the test to only assert `status` and `reason`.

Hard acceptance for review state transitions:

- A single `spec_reviewer` pass must not mark the run completed or finished.
  It should leave the run in the same blocked/review-required operator state
  until the quality review has passed or automatic review lifecycle advances it.
- `refreshReviewCompletion`, terminal invariant evaluation, or completion audit
  refresh must not convert a partially reviewed task into `state.status ===
  "completed"` just because spec review passed.
- Add a regression in `packages/orchestrator/tests/reviewRun.test.ts` that
  calls `reviewRun({ role: "spec_reviewer" })` on a blocked review-required
  task and asserts the persisted state remains `blocked` while the task records
  `review_status: "spec_review_passed"` or equivalent non-final review progress.
- Only a `quality_reviewer` pass, or the later automatic review lifecycle after
  both required review roles are satisfied, may set final checkpoint/apply-ready
  review completion fields.

- [ ] **Step 4: Implement review packet builder**

Create `packages/orchestrator/src/reviewPacket.ts`:

```ts
import type { TaskReviewArtifact, WaygentRunStateV2 } from "@waygent/contracts";

export interface ReviewTaskPacket {
  schema: "waygent.review_task_packet.v1";
  run_id: string;
  task_id: string;
  role: "spec_reviewer" | "quality_reviewer";
  checkpoint_refs: string[];
  file_claims: Array<{ path: string; mode: string }>;
  review_instruction: string;
  evidence_refs: string[];
}

export function buildReviewPacket(input: {
  state: WaygentRunStateV2;
  task_id: string;
  role: "spec_reviewer" | "quality_reviewer";
}): ReviewTaskPacket {
  const task = input.state.tasks[input.task_id];
  if (!task) throw new Error(`unknown review task: ${input.task_id}`);
  return {
    schema: "waygent.review_task_packet.v1",
    run_id: input.state.run_id,
    task_id: task.id,
    role: input.role,
    checkpoint_refs: task.checkpoint_refs,
    file_claims: task.file_claims,
    review_instruction: input.role === "spec_reviewer"
      ? "Verify the patch implements the task and spec exactly, with no missing or extra behavior."
      : "Review code quality, tests, maintainability, and fit with local patterns.",
    evidence_refs: [
      ...task.checkpoint_refs,
      ...(task.task_packet_path ? [task.task_packet_path] : [])
    ]
  };
}

export function passedReviewArtifact(input: {
  run_id: string;
  task_id: string;
  review_id: string;
  role: "spec_reviewer" | "quality_reviewer";
  evidence_refs: string[];
  reviewed_patch_refs: string[];
  model?: string;
}): TaskReviewArtifact {
  return {
    schema: "waygent.task_review.v1",
    run_id: input.run_id,
    task_id: input.task_id,
    review_id: input.review_id,
    role: input.role,
    status: "passed",
    verdict: "approved",
    issues: [],
    evidence_refs: input.evidence_refs,
    reviewed_patch_refs: input.reviewed_patch_refs,
    ...(input.model ? { model: input.model } : {}),
    created_at: new Date().toISOString()
  };
}
```

- [ ] **Step 5: Implement fake review runner**

Create `packages/orchestrator/src/reviewRunner.ts`:

```ts
import type { TaskReviewArtifact, WaygentRunStateV2 } from "@waygent/contracts";
import { writeArtifact } from "@waygent/lens-store";
import { passedReviewArtifact, type ReviewTaskPacket } from "./reviewPacket";

export async function runReviewPacket(input: {
  root: string;
  state: WaygentRunStateV2;
  packet: ReviewTaskPacket;
  dry_run?: boolean;
}): Promise<{ status: "passed"; artifact_ref: string; artifact: TaskReviewArtifact } | { status: "dry_run"; packet: ReviewTaskPacket }> {
  if (input.dry_run) return { status: "dry_run", packet: input.packet };
  const reviewId = `review_${input.packet.task_id}_${input.packet.role}_${Date.now()}`;
  const artifact = passedReviewArtifact({
    run_id: input.state.run_id,
    task_id: input.packet.task_id,
    review_id: reviewId,
    role: input.packet.role,
    evidence_refs: input.packet.evidence_refs,
    reviewed_patch_refs: input.packet.checkpoint_refs
  });
  const written = writeArtifact(
    input.state.run_root,
    `reviews/${input.packet.task_id}/${reviewId}.json`,
    `${JSON.stringify(artifact, null, 2)}\n`,
    "application/json",
    input.packet.task_id
  );
  return { status: "passed", artifact_ref: written.path, artifact };
}
```

This first runner uses deterministic local approval for fake/offline flows. Later live-provider review can replace the internals without changing `reviewRun` or artifact contracts.

- [ ] **Step 6: Add `reviewRun`**

Modify `packages/orchestrator/src/runCommands.ts`:

```ts
import { buildReviewPacket } from "./reviewPacket";
import { runReviewPacket } from "./reviewRunner";
```

Add interfaces and function:

```ts
export interface ReviewRunOptions extends RunCommandOptions {
  task?: string;
  role?: "spec_reviewer" | "quality_reviewer";
  dry_run?: boolean;
}

export async function reviewRun(options: ReviewRunOptions): Promise<{
  command: "review";
  run_id: string;
  task_id?: string;
  role?: string;
  status: "passed" | "blocked" | "dry_run";
  reason?: string;
  packet?: ReturnType<typeof buildReviewPacket>;
  review_ref?: string;
}> {
  const runId = resolveRunId(options);
  const stateResult = readRunStateV2Result(options.root, runId);
  const role = options.role ?? "spec_reviewer";
  if (stateResult.status !== "ok") return { command: "review", run_id: runId, role, status: "blocked", reason: stateBlocker(stateResult) };
  const state = stateResult.state;
  const taskId = options.task ?? Object.values(state.tasks).find((task) => task.review_status === "required" || task.review_status === "pending")?.id;
  if (!taskId || !state.tasks[taskId]) return { command: "review", run_id: runId, role, status: "blocked", reason: "no_reviewable_task" };
  const packet = buildReviewPacket({ state, task_id: taskId, role });
  const result = await runReviewPacket({ root: options.root, state, packet, dry_run: options.dry_run });
  if (result.status === "dry_run") return { command: "review", run_id: runId, task_id: taskId, role, status: "dry_run", packet };

  const task = state.tasks[taskId]!;
  const nextReviews = [...state.reviews, {
    schema: "runway.review_result.v1" as const,
    run_id: runId,
    task_id: taskId,
    attempt_id: result.artifact.review_id,
    provider: "fake",
    verdict: "pass" as const,
    spec_score: role === "spec_reviewer" ? 1 : 0,
    quality_score: role === "quality_reviewer" ? 1 : 0,
    findings: [],
    residual_risk: [],
    summary: `${role} passed.`
  }];
  writeRunStateV2(options.root, {
    ...state,
    reviews: nextReviews,
    tasks: {
      ...state.tasks,
      [taskId]: {
        ...task,
        review_status: role === "quality_reviewer" ? "passed" : "pending",
        review_refs: [...(task.review_refs ?? []), result.artifact_ref]
      }
    }
  });
  return { command: "review", run_id: runId, task_id: taskId, role, status: "passed", review_ref: result.artifact_ref };
}
```

- [ ] **Step 7: Wire CLI command**

Modify `apps/cli/src/index.ts` imports:

```ts
  reviewRun,
```

Add usage:

```ts
const usage = "waygent run|run-chain|status|events|inspect|explain|resume|verify|apply|review|repair|decisions|cost|watch|orphans|scaffold-plan|lint-design|lint-plan";
```

Add command usage:

```ts
review: "waygent review --run <id> [--task <task_id>] [--role spec_reviewer|quality_reviewer] [--dry-run]",
```

Add branch:

```ts
if (parsed.command === "review") {
  const options: Parameters<typeof reviewRun>[0] = runCommandOptions(parsed);
  if (typeof parsed.flags.task === "string") options.task = parsed.flags.task;
  if (parsed.flags.role === "spec_reviewer" || parsed.flags.role === "quality_reviewer") options.role = parsed.flags.role;
  if (parsed.flags["dry-run"]) options.dry_run = true;
  return reviewRun(options);
}
```

- [ ] **Step 8: Run tests**

Run: `bun test apps/cli/tests/cli.test.ts packages/orchestrator/tests/reviewRun.test.ts`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add packages/orchestrator/src/reviewPacket.ts packages/orchestrator/src/reviewRunner.ts packages/orchestrator/src/runCommands.ts packages/orchestrator/tests/reviewRun.test.ts apps/cli/src/index.ts apps/cli/tests/cli.test.ts
git commit -m "feat(cli): add Waygent review command"
```

---

### Task 6: Automatic Review Lifecycle in the Orchestrator

```yaml waygent-task
id: task_6_auto_review_lifecycle
title: Automatic review lifecycle in the orchestrator
dependencies:
  - task_4_review_evidence_completion_audit
  - task_5_review_command_packet
file_claims:
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/src/taskExecutor.ts
    mode: shared_append
  - path: packages/orchestrator/tests/orchestratorRunV2.test.ts
    mode: owned
  - path: packages/orchestrator/tests/orchestratorParallel.test.ts
    mode: owned
risk: high
verify:
  - bun test packages/orchestrator/tests/orchestratorRunV2.test.ts packages/orchestrator/tests/orchestratorParallel.test.ts
```

**Files:**
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify if needed: `packages/orchestrator/src/taskExecutor.ts`
- Test: `packages/orchestrator/tests/orchestratorRunV2.test.ts`
- Test: `packages/orchestrator/tests/orchestratorParallel.test.ts`

**Implementation guardrails discovered during Waygent retry:**
- Do not call `artifactReferenceFromRunRef` from `packages/orchestrator/src/orchestrator.ts`; that helper is local to `taskExecutor.ts` and is not exported.
- When recording review packet/result/provider artifacts in `orchestrator.ts`, prefer the artifacts already returned by `writeArtifact`/`runTaskReview` and wrap them directly with `artifactIndexEntry`.
- If an existing run-relative ref must be indexed from `orchestrator.ts`, import `resolveRunArtifactPath` from `./checkpointArtifacts` and compute a local artifact reference from `readFileSync(...)` plus the existing `sha256` helper. Do not invent an unimported helper name.
- Before returning task 6, run `rg -n "artifactReferenceFromRunRef" packages/orchestrator/src/orchestrator.ts` and require no matches.
- Preserve the existing crash-path completion audit behavior in
  `packages/orchestrator/tests/orchestratorParallel.test.ts`. Automatic review
  scheduling must not leave provider-crash safe-wave runs without
  `state.completion_audit`; crash/sibling-evidence tests expect a failed
  completion audit object, not `undefined`.
- Preserve existing review evidence. If a task already has valid
  `initial_reviews`, `state.reviews`, or `review_refs` satisfying the review
  evidence policy, automatic review scheduling must be idempotent and must not
  append duplicate spec/quality review artifacts. The existing
  `passes completion audit for high-risk tasks with review evidence` test
  expects exactly one review evidence entry.

- [ ] **Step 1: Add failing orchestrator review lifecycle test**

Append to `packages/orchestrator/tests/orchestratorRunV2.test.ts`:

```ts
test("dispatches review evidence for recovered verified tasks before completion", async () => {
  const result = await runWaygent({
    root,
    workspace,
    run_id: "run_recovered_review",
    plan: [
      "```yaml waygent-task",
      "id: task_recovered",
      "title: recovered task",
      "dependencies: []",
      "file_claims:",
      "  - path: recovered.txt",
      "    mode: owned",
      "risk: medium",
      "verify:",
      "  - test -f recovered.txt",
      "```"
    ].join("\n"),
    provider_fixture: "malformed-then-success",
    profile: { provider: "fake", execution_mode: "multi-agent" }
  });

  expect(result.run_id).toBe("run_recovered_review");
  const state = readRunStateV2(root, "run_recovered_review");
  expect(state.tasks.task_recovered?.review_status).toBe("passed");
  expect(state.tasks.task_recovered?.review_refs?.length).toBeGreaterThan(0);
  expect(state.reviews.some((review) => review.task_id === "task_recovered" && review.verdict === "pass")).toBe(true);
});
```

Use the existing fake provider fixture mechanism. If `provider_fixture: "malformed-then-success"` does not exist, add the smallest fake fixture branch in the test helper used by the existing malformed-provider scenario so the first attempt records recovery and the second attempt verifies.

- [ ] **Step 2: Run test and confirm failure**

Run: `bun test packages/orchestrator/tests/orchestratorRunV2.test.ts`

Expected: FAIL because orchestrator does not auto-dispatch review evidence.

- [ ] **Step 3: Add review scheduling helper in orchestrator**

Modify `packages/orchestrator/src/orchestrator.ts` imports:

```ts
import { reviewEvidencePolicy } from "./reviewEvidence";
import { buildReviewPacket } from "./reviewPacket";
import { runReviewPacket } from "./reviewRunner";
```

Add helper near other orchestration helpers:

```ts
async function runRequiredReviews(context: RunContext, root: string): Promise<void> {
  const policy = reviewEvidencePolicy(context.state);
  for (const taskId of policy.missing_task_ids) {
    const task = context.state.tasks[taskId];
    if (!task) continue;
    for (const role of ["spec_reviewer", "quality_reviewer"] as const) {
      context.appendEvent((sequence) => buildRunEvent({
        run_id: context.state.run_id,
        sequence,
        event_type: "runway.review_dispatched",
        phase: "review",
        outcome: "running",
        summary: `${role} dispatched for ${taskId}.`,
        payload: { task_id: taskId, role }
      }));
      const packet = buildReviewPacket({ state: context.state, task_id: taskId, role });
      const result = await runReviewPacket({ root, state: context.state, packet });
      if (result.status !== "passed") {
        context.mutateState((state) => {
          state.tasks[taskId] = { ...task, status: "blocked", latest_failure_class: "review_changes_requested", review_status: "failed" };
        });
        context.appendEvent((sequence) => buildRunEvent({
          run_id: context.state.run_id,
          sequence,
          event_type: "runway.review_failed",
          phase: "review",
          outcome: "failed",
          summary: `${role} failed for ${taskId}.`,
          payload: { task_id: taskId, role, failure_class: "review_changes_requested" },
          trust_impact: "requires_review"
        }));
        return;
      }
      context.mutateState((state) => {
        const current = state.tasks[taskId]!;
        state.reviews.push({
          schema: "runway.review_result.v1",
          run_id: state.run_id,
          task_id: taskId,
          attempt_id: result.artifact.review_id,
          provider: "fake",
          verdict: "pass",
          spec_score: role === "spec_reviewer" ? 1 : 0,
          quality_score: role === "quality_reviewer" ? 1 : 0,
          findings: [],
          residual_risk: [],
          summary: `${role} passed.`
        });
        state.tasks[taskId] = {
          ...current,
          review_status: role === "quality_reviewer" ? "passed" : "pending",
          review_refs: [...(current.review_refs ?? []), result.artifact_ref]
        };
      });
      context.appendEvent((sequence) => buildRunEvent({
        run_id: context.state.run_id,
        sequence,
        event_type: "runway.review_result",
        phase: "review",
        outcome: "success",
        summary: `${role} passed for ${taskId}.`,
        payload: { task_id: taskId, role, review_ref: result.artifact_ref }
      }));
    }
  }
}
```

Use the actual run context type and mutation helpers already present in `orchestrator.ts`.

- [ ] **Step 4: Call review scheduling before completion audit**

In `packages/orchestrator/src/orchestrator.ts`, immediately before `buildCompletionAudit`, run:

```ts
await runRequiredReviews(context, options.root);
context.flushState();
```

Ensure `state.current_phase = "review"` while reviews run and set it back to `"complete"` before completion audit.

- [ ] **Step 5: Run orchestrator tests**

Run: `bun test packages/orchestrator/tests/orchestratorRunV2.test.ts packages/orchestrator/tests/orchestratorParallel.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator/src/orchestrator.ts packages/orchestrator/src/taskExecutor.ts packages/orchestrator/tests/orchestratorRunV2.test.ts packages/orchestrator/tests/orchestratorParallel.test.ts
git commit -m "feat(orchestrator): auto-review recovered tasks"
```

---

### Task 7: Repair-First and Salvage-First Recovery Policy

```yaml waygent-task
id: task_7_repair_salvage_policy
title: Repair-first and salvage-first recovery policy
dependencies:
  - task_1_contracts_closure_review_cost
  - task_5_review_command_packet
file_claims:
  - path: packages/orchestrator/src/recoveryExecutor.ts
    mode: owned
  - path: packages/orchestrator/src/salvage.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/src/index.ts
    mode: owned
  - path: packages/orchestrator/tests/recoveryExecutor.test.ts
    mode: owned
  - path: packages/orchestrator/tests/salvage.test.ts
    mode: owned
risk: high
verify:
  - bun test packages/orchestrator/tests/recoveryExecutor.test.ts packages/orchestrator/tests/salvage.test.ts
```

**Files:**
- Create: `packages/orchestrator/src/salvage.ts`
- Modify: `packages/orchestrator/src/recoveryExecutor.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Test: `packages/orchestrator/tests/recoveryExecutor.test.ts`
- Test: `packages/orchestrator/tests/salvage.test.ts`

- [ ] **Step 1: Add failing recovery policy tests**

Append to `packages/orchestrator/tests/recoveryExecutor.test.ts`:

```ts
test("uses repair for review failures with patch evidence", () => {
  const decision = selectRepairAction({
    failure_class: "review_changes_requested",
    prior_worker_result: {
      schema: "runway.worker_result.v1",
      task_id: "task_a",
      candidate_id: "candidate_task_a",
      status: "completed",
      changed_files: ["a.ts"],
      summary: "Implemented.",
      evidence: { patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff" }
    },
    repair_budget: { max_attempts: 2, current: 0 }
  });

  expect(decision).toMatchObject({ action: "dispatch_repair", attempt_number: 1 });
});

test("does not full-retry malformed output when patch can be salvaged", () => {
  expect(nextRecoveryAction("malformed_result", 0, {
    prior_summary: "provider emitted malformed JSON but patch_ref is present"
  }).action).toBe("salvage_patch_then_review");
});
```

- [ ] **Step 2: Add failing salvage tests**

Create `packages/orchestrator/tests/salvage.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { classifySalvage } from "../src/salvage";

describe("salvage classification", () => {
  test("classifies adapter crash with patch ref as salvaged patch", () => {
    expect(classifySalvage({
      task_id: "task_a",
      attempt_id: "attempt_task_a_1",
      failure_class: "adapter_crashed",
      patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
      changed_files: ["a.ts"],
      evidence_refs: ["artifacts/provider/attempt_task_a_1.stderr.txt"]
    })).toEqual({
      schema: "waygent.salvage_result.v1",
      task_id: "task_a",
      attempt_id: "attempt_task_a_1",
      status: "salvaged_patch",
      patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
      changed_files: ["a.ts"],
      reason: null,
      evidence_refs: ["artifacts/provider/attempt_task_a_1.stderr.txt"]
    });
  });
});
```

- [ ] **Step 3: Run tests and confirm failure**

Run: `bun test packages/orchestrator/tests/recoveryExecutor.test.ts packages/orchestrator/tests/salvage.test.ts`

Expected: FAIL because recovery action enum and salvage helper do not exist.

- [ ] **Step 4: Extend recovery actions**

Modify `packages/orchestrator/src/recoveryExecutor.ts`:

```ts
export type RecoveryAction =
  | "dispatch_repair"
  | "salvage_patch_then_review"
  | "retry_with_strict_prompt"
  | "retry_with_evidence"
  | "request_decision"
  | "halt";
```

Update `selectRepairAction`:

```ts
if (input.failure_class !== "verification_failed" && input.failure_class !== "review_changes_requested" && input.failure_class !== "diff_scope_failed") return null;
```

Update `nextRecoveryAction` before the default policy lookup:

```ts
if (
  (failure_class === "malformed_result" || failure_class === "adapter_crashed" || failure_class === "timeout")
  && (options.prior_summary ?? "").includes("patch_ref")
) {
  return {
    action: "salvage_patch_then_review",
    attempt_number: prior_attempts + 1,
    max_attempts: 1
  };
}
```

- [ ] **Step 5: Implement salvage helper**

Create `packages/orchestrator/src/salvage.ts`:

```ts
import type { FailureClass, SalvageResult } from "@waygent/contracts";

export function classifySalvage(input: {
  task_id: string;
  attempt_id: string;
  failure_class: FailureClass | string;
  patch_ref: string | null;
  changed_files: string[];
  evidence_refs: string[];
}): SalvageResult {
  const salvageableFailure = input.failure_class === "adapter_crashed"
    || input.failure_class === "malformed_result"
    || input.failure_class === "timeout"
    || input.failure_class === "diff_scope_failed";
  if (salvageableFailure && input.patch_ref && input.changed_files.length > 0) {
    return {
      schema: "waygent.salvage_result.v1",
      task_id: input.task_id,
      attempt_id: input.attempt_id,
      status: "salvaged_patch",
      patch_ref: input.patch_ref,
      changed_files: input.changed_files,
      reason: null,
      evidence_refs: input.evidence_refs
    };
  }
  return {
    schema: "waygent.salvage_result.v1",
    task_id: input.task_id,
    attempt_id: input.attempt_id,
    status: "no_patch",
    patch_ref: null,
    changed_files: input.changed_files,
    reason: "no_salvageable_patch",
    evidence_refs: input.evidence_refs
  };
}
```

- [ ] **Step 6: Emit salvage events in orchestrator**

In `packages/orchestrator/src/orchestrator.ts`, when a rejected wave result or malformed worker output has patch evidence, write a salvage artifact and append:

```ts
context.appendEvent((sequence) => buildRunEvent({
  run_id: runId,
  sequence,
  event_type: "runway.patch_salvaged",
  phase: "recover",
  outcome: salvage.status === "salvaged_patch" ? "success" : "blocked",
  summary: salvage.status === "salvaged_patch" ? "Patch salvaged for review." : "No salvageable patch was found.",
  payload: salvage,
  trust_impact: "requires_review"
}));
```

Route `salvaged_patch` to review before checkpoint. Do not mark it as a completed implementation without review.

- [ ] **Step 7: Run tests**

Run: `bun test packages/orchestrator/tests/recoveryExecutor.test.ts packages/orchestrator/tests/salvage.test.ts`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/orchestrator/src/recoveryExecutor.ts packages/orchestrator/src/salvage.ts packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/recoveryExecutor.test.ts packages/orchestrator/tests/salvage.test.ts
git commit -m "feat(orchestrator): prefer repair and salvage recovery"
```

---

### Task 8: Budget Policy and Cost Projection

```yaml waygent-task
id: task_8_budget_policy_cost_projection
title: Budget policy and cost projection
dependencies:
  - task_1_contracts_closure_review_cost
file_claims:
  - path: packages/orchestrator/src/budgetPolicy.ts
    mode: owned
  - path: packages/orchestrator/src/index.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/src/runCommands.ts
    mode: owned
  - path: packages/orchestrator/tests/budgetPolicy.test.ts
    mode: owned
  - path: packages/orchestrator/tests/runCommandsV2.test.ts
    mode: owned
  - path: apps/cli/src/index.ts
    mode: owned
  - path: apps/cli/tests/cli.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/budgetPolicy.test.ts packages/orchestrator/tests/runCommandsV2.test.ts apps/cli/tests/cli.test.ts
```

**Files:**
- Create: `packages/orchestrator/src/budgetPolicy.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `apps/cli/src/index.ts`
- Test: `packages/orchestrator/tests/budgetPolicy.test.ts`
- Test: `packages/orchestrator/tests/runCommandsV2.test.ts`
- Test: `apps/cli/tests/cli.test.ts`

- [ ] **Step 1: Add failing budget policy tests**

Create `packages/orchestrator/tests/budgetPolicy.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { evaluateBudgetPolicy } from "../src/budgetPolicy";

describe("budget policy", () => {
  test("warns at configured threshold", () => {
    expect(evaluateBudgetPolicy({
      cost_usd: 57,
      dispatches: 3,
      budget_cap_usd: null,
      budget_action: "warn"
    })).toEqual({
      budget_status: "warning",
      should_pause: false,
      warning_threshold: 50,
      reason: "cost_warning"
    });
  });

  test("pauses when cap is exceeded and action is pause", () => {
    expect(evaluateBudgetPolicy({
      cost_usd: 101,
      dispatches: 6,
      budget_cap_usd: 100,
      budget_action: "pause"
    })).toMatchObject({
      budget_status: "paused",
      should_pause: true,
      reason: "budget_cap_exceeded"
    });
  });
});
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `bun test packages/orchestrator/tests/budgetPolicy.test.ts`

Expected: FAIL because `budgetPolicy.ts` does not exist.

- [ ] **Step 3: Implement budget policy**

Create `packages/orchestrator/src/budgetPolicy.ts`:

```ts
export interface BudgetPolicyInput {
  cost_usd: number;
  dispatches: number;
  budget_cap_usd: number | null;
  budget_action: "warn" | "pause" | "off" | undefined;
}

export interface BudgetPolicyResult {
  budget_status: "ok" | "warning" | "paused" | "exhausted";
  should_pause: boolean;
  warning_threshold: number | null;
  reason: string | null;
}

const WARNING_THRESHOLDS = [50, 100, 250, 500];

export function evaluateBudgetPolicy(input: BudgetPolicyInput): BudgetPolicyResult {
  if (input.budget_action === "off") {
    return { budget_status: "ok", should_pause: false, warning_threshold: null, reason: null };
  }
  if (typeof input.budget_cap_usd === "number" && input.cost_usd >= input.budget_cap_usd) {
    return {
      budget_status: input.budget_action === "pause" ? "paused" : "exhausted",
      should_pause: input.budget_action === "pause",
      warning_threshold: input.budget_cap_usd,
      reason: "budget_cap_exceeded"
    };
  }
  const threshold = WARNING_THRESHOLDS.find((value) => input.cost_usd >= value) ?? null;
  if (threshold !== null) {
    return {
      budget_status: "warning",
      should_pause: false,
      warning_threshold: threshold,
      reason: "cost_warning"
    };
  }
  return { budget_status: "ok", should_pause: false, warning_threshold: null, reason: null };
}
```

- [ ] **Step 4: Wire cost summary into `costRun` and operator projection**

Modify `packages/orchestrator/src/runCommands.ts`:

```ts
import { evaluateBudgetPolicy } from "./budgetPolicy";
```

Extend `costRun` return object:

```ts
const totals = state.state.cost_ledger?.totals;
const budget = evaluateBudgetPolicy({
  cost_usd: totals?.cost_usd ?? 0,
  dispatches: totals?.dispatches ?? 0,
  budget_cap_usd: state.state.budget_cap_usd ?? null,
  budget_action: state.state.budget_action
});
return {
  run_id: runId,
  cost_ledger: state.state.cost_ledger ?? null,
  budget_cap_usd: state.state.budget_cap_usd ?? null,
  budget_action: state.state.budget_action ?? null,
  cost_summary: {
    cost_usd: totals?.cost_usd ?? 0,
    dispatches: totals?.dispatches ?? 0,
    budget_status: budget.budget_status
  }
};
```

Modify `packages/lens-projectors/src/operatorDecision.ts` in the projection return:

```ts
    cost_summary: costSummaryFromState(state),
```

Add helper:

```ts
function costSummaryFromState(state: WaygentRunStateV2): NonNullable<OperatorDecisionProjection["cost_summary"]> {
  const totals = state.cost_ledger?.totals;
  const cost = totals?.cost_usd ?? 0;
  const budgetStatus = state.budget_action === "pause" && typeof state.budget_cap_usd === "number" && cost >= state.budget_cap_usd
    ? "paused"
    : cost >= 50
      ? "warning"
      : "ok";
  return {
    cost_usd: cost,
    dispatches: totals?.dispatches ?? 0,
    budget_status: budgetStatus
  };
}
```

- [ ] **Step 5: Emit budget events in orchestrator**

In `packages/orchestrator/src/orchestrator.ts`, after `platform.cost_accumulated`, evaluate budget. When warning:

Implementation guardrail: the `budget` value used in the
`platform.cost_accumulated` payload must be computed inside
`recordRuntimeEvidence` after the cost ledger mutation, before appending the
event. Do not place this local variable in `replayTaskExecutionFailure`; that
leaves `recordRuntimeEvidence` with `cost_summary: budget` and causes CLI
run/status/events tests to fail with `ReferenceError: budget is not defined`.

```ts
context.appendEvent((sequence) => buildRunEvent({
  run_id: runId,
  sequence,
  event_type: "platform.budget_warning",
  phase: "cost",
  outcome: "success",
  summary: "Run cost crossed a budget warning threshold.",
  payload: { cost_summary: budget },
  trust_impact: "neutral"
}));
```

When pause:

```ts
context.appendEvent((sequence) => buildRunEvent({
  run_id: runId,
  sequence,
  event_type: "platform.budget_paused",
  phase: "cost",
  outcome: "blocked",
  summary: "Run paused because budget cap was exceeded.",
  payload: { cost_summary: budget },
  trust_impact: "requires_review"
}));
```

- [ ] **Step 6: Run tests**

Run: `bun test packages/orchestrator/tests/budgetPolicy.test.ts packages/orchestrator/tests/runCommandsV2.test.ts apps/cli/tests/cli.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/orchestrator/src/budgetPolicy.ts packages/orchestrator/src/orchestrator.ts packages/orchestrator/src/runCommands.ts packages/orchestrator/tests/budgetPolicy.test.ts packages/orchestrator/tests/runCommandsV2.test.ts apps/cli/src/index.ts apps/cli/tests/cli.test.ts
git commit -m "feat(orchestrator): surface Waygent budget policy"
```

---

### Task 9: Stale Run and Orphan Cleanup

```yaml waygent-task
id: task_9_stale_run_orphan_cleanup
title: Stale run and orphan cleanup
dependencies:
  - task_1_contracts_closure_review_cost
file_claims:
  - path: packages/orchestrator/src/orphanRuns.ts
    mode: owned
  - path: packages/orchestrator/src/runCommands.ts
    mode: owned
  - path: apps/cli/src/index.ts
    mode: owned
  - path: packages/orchestrator/tests/orphanRuns.test.ts
    mode: owned
  - path: apps/cli/tests/cli.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/orphanRuns.test.ts apps/cli/tests/cli.test.ts
```

**Files:**
- Modify: `packages/orchestrator/src/orphanRuns.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `apps/cli/src/index.ts`
- Test: `packages/orchestrator/tests/orphanRuns.test.ts`
- Test: `apps/cli/tests/cli.test.ts`

- [ ] **Step 1: Add failing stale run tests**

Create or extend `packages/orchestrator/tests/orphanRuns.test.ts`:

```ts
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { classifyStaleRun, markStaleRunBlocked } from "../src/orphanRuns";
import { baseV2State } from "./support/runStateFixture";

describe("stale run classification", () => {
  test("classifies old running run with missing provider process as stale", () => {
    const state = baseV2State({ root: "/tmp/waygent", run_id: "run_stale" });
    state.status = "running";
    state.current_phase = "dispatch";
    state.timestamps.updated_at = "2026-05-25T00:00:00.000Z";

    expect(classifyStaleRun(state, new Date("2026-05-26T00:00:00.000Z"))).toEqual({
      run_id: "run_stale",
      stale: true,
      reason: "heartbeat_expired",
      safe_actions: ["inspect", "mark_blocked"]
    });
  });

  test("marks stale run blocked without deleting artifacts", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-stale-"));
    const state = baseV2State({ root, run_id: "run_stale" });
    state.status = "running";
    const runRoot = join(root, "run_stale");
    mkdirSync(runRoot, { recursive: true });
    writeFileSync(join(runRoot, "state.json"), `${JSON.stringify(state, null, 2)}\n`);

    const result = markStaleRunBlocked({ root, run_id: "run_stale", reason: "heartbeat_expired" });
    expect(result).toMatchObject({ run_id: "run_stale", status: "blocked" });
  });
});
```

- [ ] **Step 2: Add failing CLI test**

Append to `apps/cli/tests/cli.test.ts`:

```ts
test("parses stale orphan flags", () => {
  expect(parseCli(["orphans", "--stale", "--mark-blocked", "run_stale"])).toEqual({
    command: "orphans",
    flags: {
      stale: true,
      "mark-blocked": "run_stale"
    }
  });
});
```

- [ ] **Step 3: Run tests and confirm failure**

Run: `bun test packages/orchestrator/tests/orphanRuns.test.ts apps/cli/tests/cli.test.ts`

Expected: FAIL because stale classification and flags are not implemented.

- [ ] **Step 4: Implement stale classification**

Modify `packages/orchestrator/src/orphanRuns.ts`:

```ts
import type { StaleRunStatus, WaygentRunStateV2 } from "@waygent/contracts";
```

Add:

```ts
const STALE_MS = 60 * 60 * 1000;

export function classifyStaleRun(state: WaygentRunStateV2, now = new Date()): StaleRunStatus {
  if (state.status !== "running" && state.status !== "initializing" && state.status !== "applying") {
    return { run_id: state.run_id, stale: false, reason: "active", safe_actions: ["inspect"] };
  }
  const updated = Date.parse(state.timestamps.updated_at);
  if (Number.isFinite(updated) && now.getTime() - updated > STALE_MS) {
    return {
      run_id: state.run_id,
      stale: true,
      reason: "heartbeat_expired",
      safe_actions: ["inspect", "mark_blocked"]
    };
  }
  return { run_id: state.run_id, stale: false, reason: "active", safe_actions: ["inspect", "resume"] };
}

export function markStaleRunBlocked(input: { root: string; run_id: string; reason: StaleRunStatus["reason"] }): {
  run_id: string;
  status: "blocked";
  reason: string;
} {
  const statePath = join(input.root, input.run_id, "state.json");
  const state = JSON.parse(readFileSync(statePath, "utf8")) as WaygentRunStateV2;
  const next: WaygentRunStateV2 = {
    ...state,
    status: "blocked",
    lifecycle_outcome: "blocked",
    current_phase: state.current_phase,
    stale_run_status: {
      run_id: state.run_id,
      stale: true,
      reason: input.reason,
      safe_actions: ["inspect"]
    },
    timestamps: {
      ...state.timestamps,
      updated_at: new Date().toISOString(),
      completed_at: new Date().toISOString()
    }
  };
  writeFileSync(statePath, `${JSON.stringify(next, null, 2)}\n`);
  return { run_id: input.run_id, status: "blocked", reason: input.reason };
}
```

- [ ] **Step 5: Extend `orphansRun` and CLI flags**

Modify `packages/orchestrator/src/runCommands.ts`:

```ts
import { classifyStaleRun, markStaleRunBlocked } from "./orphanRuns";
```

Extend `orphansRun` options and branch:

```ts
export function orphansRun(options: RunCommandOptions & {
  delete?: string;
  yes?: boolean;
  stale?: boolean;
  mark_blocked?: string;
}): unknown {
  if (options.mark_blocked) {
    return markStaleRunBlocked({ root: options.root, run_id: options.mark_blocked, reason: "heartbeat_expired" });
  }
  const advisory = scanOrphanRuns({ root: options.root });
  if (options.stale) {
    return {
      ...advisory,
      stale_runs: scanStaleRuns(options.root).map((state) => classifyStaleRun(state))
    };
  }
  if (options.delete) return deleteResolvedOrphan({ root: options.root, id: options.delete, yes: Boolean(options.yes), advisory });
  return advisory;
}
```

Add `scanStaleRuns(root)` in `orphanRuns.ts` to parse valid run states and return `WaygentRunStateV2[]`.

Modify `apps/cli/src/index.ts`:

```ts
orphans: "waygent orphans [--root <run_root>] [--stale] [--mark-blocked <id>] [--delete <id> --yes]",
```

And:

```ts
if (parsed.flags.stale) orphanOptions.stale = true;
if (typeof parsed.flags["mark-blocked"] === "string") orphanOptions.mark_blocked = parsed.flags["mark-blocked"];
```

- [ ] **Step 6: Run tests**

Run: `bun test packages/orchestrator/tests/orphanRuns.test.ts apps/cli/tests/cli.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/orchestrator/src/orphanRuns.ts packages/orchestrator/src/runCommands.ts packages/orchestrator/tests/orphanRuns.test.ts apps/cli/src/index.ts apps/cli/tests/cli.test.ts
git commit -m "feat(orchestrator): classify stale Waygent runs"
```

---

### Task 10: Integration Fixtures and Scenario Coverage

```yaml waygent-task
id: task_10_integration_fixtures
title: Integration fixtures and scenario coverage
dependencies:
  - task_2_verification_resolution_apply_readiness
  - task_3_trust_read_model_consistency
  - task_6_auto_review_lifecycle
  - task_7_repair_salvage_policy
  - task_8_budget_policy_cost_projection
  - task_9_stale_run_orphan_cleanup
file_claims:
  - path: tests/waygent-scenarios/stale-verification-recovered.json
    mode: owned
  - path: tests/waygent-scenarios/missing-review-evidence.json
    mode: owned
  - path: tests/waygent-scenarios/review-pass-apply-ready.json
    mode: owned
  - path: tests/waygent-scenarios/budget-paused.json
    mode: owned
  - path: tests/waygent-scenarios/salvaged-patch-needs-review.json
    mode: owned
  - path: tests/integration/waygent-scenarios.test.ts
    mode: owned
  - path: tests/integration/waygent-fixture-lab.test.ts
    mode: owned
  - path: tests/integration/waygent-dogfood-evidence.test.ts
    mode: owned
  - path: packages/testkit/src/waygentScenarioHarness.ts
    mode: owned
  - path: packages/testkit/tests/waygentScenarioHarness.test.ts
    mode: owned
risk: high
verify:
  - bun run waygent:scenarios
  - bun run waygent:fixture-lab
  - bun run waygent:dogfood
```

**Files:**
- Create: `tests/waygent-scenarios/stale-verification-recovered.json`
- Create: `tests/waygent-scenarios/missing-review-evidence.json`
- Create: `tests/waygent-scenarios/review-pass-apply-ready.json`
- Create: `tests/waygent-scenarios/budget-paused.json`
- Create: `tests/waygent-scenarios/salvaged-patch-needs-review.json`
- Modify: `tests/integration/waygent-scenarios.test.ts`
- Modify: `tests/integration/waygent-fixture-lab.test.ts`
- Modify: `tests/integration/waygent-dogfood-evidence.test.ts`
- Modify: `packages/testkit/src/waygentScenarioHarness.ts`
- Test: `packages/testkit/tests/waygentScenarioHarness.test.ts`

- [ ] **Step 0: Keep scenario replay deterministic and bounded**

The golden scenario tests must complete under Bun's normal 30s per-test timeout.
Do not solve timeout failures by only raising `--timeout`.

In `packages/testkit/src/waygentScenarioHarness.ts`, fault-injection scenarios
must not repeatedly invoke a full `runWaygent(...)` runtime run. Any scenario
with one of these flags should be replayed through deterministic in-memory
state/event projection:

- `source_dirty_before_apply`
- `force_missing_checkpoint`
- `checkpoint_dry_run_conflict`
- `stale_verification_recovered`
- `missing_review_evidence`
- `review_pass_apply_ready`
- `budget_paused`
- `salvaged_patch_needs_review`

The same deterministic replay rule applies to the pre-existing fault fixtures
that do not yet expose one of those boolean flags. At minimum, these fixture ids
must not call the full runtime runner inside `bun run waygent:scenarios`:

- `checkpoint-dry-run-conflict`
- `dependency-missing`
- `dirty-apply-block`
- `malformed-provider`
- `missing-checkpoint`
- `overlapping-claims`

Provider fixture names that encode failure/recovery behavior must also route to
synthetic replay unless the test explicitly opts into a slow smoke run:

- `verification-fail-then-pass`
- `malformed-then-success`
- `review-pass-after-recovery`
- `adapter-crash-with-patch`
- any dependency-missing, malformed-output, dirty-apply, missing-checkpoint,
  overlapping-claims, or checkpoint-conflict fixture variant

Reserve a real fake-provider runtime call only for the minimal baseline smoke
scenario. The synthetic/fault replay path must still assert the same
operator-decision, apply-readiness, checkpoint, recovered-failure, and provider
attempt projections. Add harness tests that prove every fault fixture listed
above does not call the runtime runner and completes synchronously. The
`waygent scenario golden replays` test suite must not contain any fixture that
spends the full 30s Bun timeout in normal operation; if a fixture needs a runtime
smoke test, move that fixture behind an explicit slow-test opt-in instead of
leaving it in the default golden replay loop.

- [ ] **Step 1: Add scenario fixture for stale verification**

Create `tests/waygent-scenarios/stale-verification-recovered.json`:

```json
{
  "id": "stale-verification-recovered",
  "title": "Recovered verification failure is not current blocker",
  "provider_fixture": "verification-fail-then-pass",
  "source_dirty_before_apply": false,
  "force_missing_checkpoint": false,
  "plan": "```yaml waygent-task\nid: task_recovered_verify\ntitle: recovered verify task\ndependencies: []\nfile_claims:\n  - path: recovered.txt\n    mode: owned\nrisk: medium\nverify:\n  - test -f recovered.txt\n```",
  "expected": {
    "run_status": "blocked",
    "apply_status": "blocked",
    "primary_blocker": "review_evidence_missing",
    "forbidden_blockers": ["verification_failed"],
    "trust_status": "needs_review",
    "recovered_failure_count": 1
  }
}
```

- [ ] **Step 2: Add scenario fixture for missing review evidence**

Create `tests/waygent-scenarios/missing-review-evidence.json`:

```json
{
  "id": "missing-review-evidence",
  "title": "Recovered task requires review evidence",
  "provider_fixture": "malformed-then-success",
  "source_dirty_before_apply": false,
  "force_missing_checkpoint": false,
  "plan": "```yaml waygent-task\nid: task_needs_review\ntitle: task needing review\ndependencies: []\nfile_claims:\n  - path: review.txt\n    mode: owned\nrisk: medium\nverify:\n  - test -f review.txt\n```",
  "expected": {
    "run_status": "blocked",
    "apply_status": "blocked",
    "primary_blocker": "review_evidence_missing",
    "review_status": {
      "required": true,
      "missing_task_ids": ["task_needs_review"]
    }
  }
}
```

- [ ] **Step 3: Add review-pass apply-ready scenario**

Create `tests/waygent-scenarios/review-pass-apply-ready.json`:

```json
{
  "id": "review-pass-apply-ready",
  "title": "Review evidence closes recovery audit",
  "provider_fixture": "review-pass-after-recovery",
  "source_dirty_before_apply": false,
  "force_missing_checkpoint": false,
  "plan": "```yaml waygent-task\nid: task_review_pass\ntitle: review pass task\ndependencies: []\nfile_claims:\n  - path: review-pass.txt\n    mode: owned\nrisk: medium\nverify:\n  - test -f review-pass.txt\n```",
  "expected": {
    "run_status": "completed",
    "apply_status": "ready",
    "primary_blocker": null,
    "trust_status": "trusted",
    "review_status": {
      "required": true,
      "missing_task_ids": [],
      "passed_task_ids": ["task_review_pass"]
    }
  }
}
```

- [ ] **Step 4: Add budget-paused and salvage scenarios**

Create `tests/waygent-scenarios/budget-paused.json`:

```json
{
  "id": "budget-paused",
  "title": "Budget cap pauses run",
  "provider_fixture": "expensive-success",
  "source_dirty_before_apply": false,
  "force_missing_checkpoint": false,
  "budget_cap_usd": 50,
  "budget_action": "pause",
  "plan": "```yaml waygent-task\nid: task_budget\ntitle: budget task\ndependencies: []\nfile_claims:\n  - path: budget.txt\n    mode: owned\nrisk: low\nverify:\n  - test -f budget.txt\n```",
  "expected": {
    "run_status": "blocked",
    "primary_blocker": "cost_budget_exhausted",
    "budget_status": "paused"
  }
}
```

Create `tests/waygent-scenarios/salvaged-patch-needs-review.json`:

```json
{
  "id": "salvaged-patch-needs-review",
  "title": "Adapter crash salvage requires review",
  "provider_fixture": "adapter-crash-with-patch",
  "source_dirty_before_apply": false,
  "force_missing_checkpoint": false,
  "plan": "```yaml waygent-task\nid: task_salvage\ntitle: salvage task\ndependencies: []\nfile_claims:\n  - path: salvage.txt\n    mode: owned\nrisk: medium\nverify:\n  - test -f salvage.txt\n```",
  "expected": {
    "run_status": "blocked",
    "allowed_primary_blockers": ["review_evidence_missing", "provider_not_ready"],
    "operator_allowed_actions_must_include": ["run_review"],
    "expected_event_types": ["runway.patch_salvaged"]
  }
}
```

For `salvaged-patch-needs-review`, do not make the golden overly brittle by
requiring `review_evidence_missing` as the sole primary blocker. A salvaged
patch can surface `provider_not_ready` first when provider readiness is the
earliest operator blocker. The fixture must still prove the important behavior:
the salvage event is present and review is available/required before apply.

Also update the pre-existing `tests/waygent-scenarios/malformed-provider.json`
golden to use `event_types_must_include` instead of an exact `event_types`
sequence. The number of recovery retries is a runtime policy detail and may be
two or three attempts; the fixture should assert the durable contract only:
run starts, malformed worker failure is observed, recovery is scheduled, a
later worker attempt succeeds or recovery eventually requires decision, and the
trust report is updated when blocked. Do not require a full event list equality
for this scenario. Remove exact `total_events` and exact `provider_attempts`
length assertions from that fixture as well, because those encode the retry
budget rather than the observable malformed-provider contract.

Also update the pre-existing `tests/waygent-scenarios/dependency-missing.json`
golden so the new automatic-review lifecycle is not treated as an unexpected
event. Prefer `event_types_must_include` over exact `event_types`; if an exact
list remains necessary, include `runway.review_required` after
`runway.recovery_decision_required` and before `lens.trust_report_updated`.
This fixture should assert the durable dependency-missing contract, not the
absence of review lifecycle evidence.

- [ ] **Step 5: Extend scenario harness expected fields**

Modify `packages/testkit/src/waygentScenarioHarness.ts`:

```ts
export interface WaygentScenarioExpected {
  primary_blocker?: string | null;
  allowed_primary_blockers?: string[];
  operator_allowed_actions_must_include?: string[];
  forbidden_blockers?: string[];
  trust_status?: string;
  recovered_failure_count?: number;
  budget_status?: string;
  review_status?: {
    required?: boolean;
    missing_task_ids?: string[];
    passed_task_ids?: string[];
  };
}
```

When normalizing actual results:

```ts
normalized.primary_blocker = operatorDecision.primary_blocker?.code ?? null;
normalized.trust_status = replay.trust_report?.trust_status ?? runStatus.trust_status;
normalized.recovered_failure_count = operatorDecision.recovered_failures?.length ?? 0;
normalized.budget_status = operatorDecision.cost_summary?.budget_status ?? null;
normalized.review_status = operatorDecision.review_status ?? null;
```

- [ ] **Step 6: Add assertions in integration test**

Modify `tests/integration/waygent-scenarios.test.ts`:

```ts
if (expected.primary_blocker !== undefined) expect(actual.primary_blocker).toBe(expected.primary_blocker);
if (expected.allowed_primary_blockers) expect(expected.allowed_primary_blockers).toContain(actual.primary_blocker);
if (expected.operator_allowed_actions_must_include) {
  for (const action of expected.operator_allowed_actions_must_include) {
    expect(actual.operator_allowed_actions).toContain(action);
  }
}
if (expected.forbidden_blockers) expect(expected.forbidden_blockers).not.toContain(actual.primary_blocker);
if (expected.trust_status !== undefined) expect(actual.trust_status).toBe(expected.trust_status);
if (expected.recovered_failure_count !== undefined) expect(actual.recovered_failure_count).toBe(expected.recovered_failure_count);
if (expected.budget_status !== undefined) expect(actual.budget_status).toBe(expected.budget_status);
if (expected.review_status?.missing_task_ids) expect(actual.review_status?.missing_task_ids).toEqual(expected.review_status.missing_task_ids);
if (expected.review_status?.passed_task_ids) expect(actual.review_status?.passed_task_ids).toEqual(expected.review_status.passed_task_ids);
```

For fixture-lab stale verification trust tests, pass representative verification
events into `projectTrustReport`. A bare synthetic state with `events: []` is
expected to remain `insufficient_evidence`; it must not be asserted as
`trusted` unless kernel/verification evidence is present.

- [ ] **Step 7: Run integration gates**

Run: `bun run waygent:scenarios`

Expected: PASS.

Run: `bun run waygent:fixture-lab`

Expected: PASS.

Run: `bun run waygent:dogfood`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/waygent-scenarios tests/integration packages/testkit/src packages/testkit/tests
git commit -m "test(waygent): cover closure review cost scenarios"
```

---

### Task 11: Documentation, Graphify, and Full Verification

```yaml waygent-task
id: task_11_docs_graphify_full_verification
title: Documentation, Graphify, and full verification
dependencies:
  - task_10_integration_fixtures
file_claims:
  - path: docs/operations/verification.md
    mode: owned
  - path: docs/operations/waygent.md
    mode: owned
  - path: skills/waygent/SKILL.md
    mode: owned
  - path: graphify-out/GRAPH_REPORT.md
    mode: owned
  - path: graphify-out/graph.json
    mode: owned
  - path: packages/lens-projectors/src/operatorDecision.ts
    mode: owned
  - path: packages/lens-projectors/src/runReadModel.ts
    mode: owned
  - path: packages/lens-projectors/src/trust.ts
    mode: owned
  - path: packages/lens-projectors/tests/runReadModel.test.ts
    mode: owned
  - path: packages/orchestrator/src/budgetPolicy.ts
    mode: owned
  - path: packages/orchestrator/src/completionAudit.ts
    mode: owned
  - path: packages/orchestrator/src/index.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/src/orphanRuns.ts
    mode: owned
  - path: packages/orchestrator/src/recoveryExecutor.ts
    mode: owned
  - path: packages/orchestrator/src/reviewArtifacts.ts
    mode: owned
  - path: packages/orchestrator/src/reviewEvidence.ts
    mode: owned
  - path: packages/orchestrator/src/reviewRunner.ts
    mode: owned
  - path: packages/orchestrator/src/runCommands.ts
    mode: owned
  - path: packages/orchestrator/src/salvage.ts
    mode: owned
  - path: packages/orchestrator/tests/orchestratorRunV2.test.ts
    mode: owned
  - path: packages/testkit/src/index.ts
    mode: owned
  - path: packages/testkit/src/waygentScenarioHarness.ts
    mode: owned
  - path: packages/testkit/tests/waygentScenarioHarness.test.ts
    mode: owned
  - path: apps/console/src/App.tsx
    mode: owned
  - path: apps/console/src/uiModel.test.ts
    mode: owned
risk: medium
verify:
  - bun run check
  - bun run platform:demo
  - bun run waygent:scenarios
  - bun run waygent:fixture-lab
  - bun run waygent:dogfood
  - bun run --cwd apps/console build
  - git diff --check
```

**Files:**
- Modify: `docs/operations/verification.md`
- Modify: `docs/operations/waygent.md`
- Modify: `skills/waygent/SKILL.md`
- Modify generated: `graphify-out/GRAPH_REPORT.md`
- Modify generated: `graphify-out/graph.json`
- Fix final read-model status typing if the full gate exposes a
  `review_required` mismatch in `packages/lens-projectors/src/runReadModel.ts`.
- Fix final trust projection typing in `packages/lens-projectors/src/trust.ts`
  if strict TypeScript rejects review records read from state.
- If `bun run check` reports `TS2322` in `packages/lens-projectors/src/trust.ts`
  because `TrustStatus` includes `"needs_review"` but a narrower local return
  type or projection type still excludes it, fix that type in
  `packages/lens-projectors/src/trust.ts`. Do not classify this as a missing
  `node_modules` or dependency-installation blocker.
- Fix full-gate typecheck issues found after all dependency checkpoints are
  materialized, limited to the file claims above.
- Fix final salvage optional-field schema drift in
  `packages/orchestrator/src/salvage.ts` if the full gate rejects undefined
  optional values.
- Fix final recovery action shape drift in
  `packages/orchestrator/src/recoveryExecutor.ts` if the full gate rejects
  legacy `selectRepairAction` expectations after salvage/review policy changes.
- Fix final full-gate test drift in `packages/orchestrator/tests/orchestratorRunV2.test.ts`
  when the new salvage-first policy makes recovered malformed provider output
  stop as review-required instead of retrying with a strict prompt.
- Fix final full-gate testkit typing or fixture drift in
  `packages/testkit/src/waygentScenarioHarness.ts`, `packages/testkit/src/index.ts`,
  and focused tests when earlier integration fixture checkpoints make replay
  events stricter.

- [ ] **Step 1: Update verification docs**

Modify `docs/operations/verification.md` to include:

```md
## Closure, Review, and Cost Reliability Gate

Use this gate after changes to apply readiness, review evidence, recovery,
budget policy, or stale-run cleanup:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:fixture-lab
bun run waygent:dogfood
bun run --cwd apps/console build
git diff --check
```

Expected operator behavior:

- stale verification failures are reported as recovered evidence, not active
  blockers;
- recovered tasks without review evidence block as `review_evidence_missing`;
- review-passed recovered tasks can become apply-ready;
- budget pauses emit `platform.budget_paused`;
- stale runs can be marked blocked without mutating source checkouts.
```

- [ ] **Step 2: Update Waygent operator docs**

Modify `docs/operations/waygent.md` to document:

```md
### Review-required recovered runs

When recovery succeeds but review is required, `waygent explain` reports
`review_evidence_missing`. The safe next action is:

```bash
bun run waygent -- review --run <run_id>
```

After review passes, rerun:

```bash
bun run waygent -- explain --run <run_id>
```

The run is apply-ready only when apply readiness is `ready`.
```

- [ ] **Step 3: Update Waygent skill mappings**

Modify `skills/waygent/SKILL.md` natural-language mappings:

```md
- "리뷰 실행해줘" -> `waygent review --last`
- "이 태스크 리뷰해줘" -> `waygent review --last --task <task_id>`
- "stale run 정리해줘" -> `waygent orphans --stale`
- "stale run 막힌 상태로 표시해줘" -> `waygent orphans --mark-blocked <run_id>`
```

Add stop rule:

```md
- If a run reports `review_evidence_missing`, run or recommend `waygent review`
  instead of rerunning verification.
```

- [ ] **Step 4: Run full verification**

First ensure the isolated Waygent worktree has dependencies available. If
`node_modules/` is absent, run:

```bash
bun install --frozen-lockfile
```

This is allowed inside the isolated worktree because `node_modules/` is ignored
runtime setup, not checkpoint content. Do not stage, checkpoint, or document
`node_modules/`, build outputs, package-manager caches, or tool caches as source
changes.

Then run each verification command separately:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:fixture-lab
bun run waygent:dogfood
bun run --cwd apps/console build
git diff --check
```

Expected: every command exits 0.

Dependency/build artifacts may exist in the isolated worktree after verification,
but they must remain ignored and absent from the task diff before checkpoint
sealing.

Do not run destructive cleanup commands such as `rm -rf node_modules`,
`git clean -fd`, or `git reset --hard` to satisfy the artifact-cleanliness
requirement. If verification creates ignored dependency/build outputs, leave
them ignored and confirm with `git status --short --ignored=matching` or
`git diff --check`; they must not be included in the checkpoint diff.

- [ ] **Step 5: Refresh Graphify**

Run: `graphify update .`

Expected: `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.json` update successfully.

If Graphify fails only because the tool cannot be fetched or installed from the
network/PyPI/uv cache, record that as external environment evidence and continue
to emit a valid worker result. Do not include raw install logs in the worker
result; summarize the command, status, and short failure reason. Source
verification failures still block this task.

- [ ] **Step 6: Re-run diff hygiene**

Run: `git diff --check`

Expected: no output and exit 0.

- [ ] **Step 7: Return parseable worker result**

The final worker response must be exactly one compact JSON object matching
`runway.worker_result.v1`, with no markdown fences, no raw command logs, and no
extra prose.

Allowed `status` values for this task are only:

- `completed` when source verification passes and checkpoint diff hygiene is
  clean, even if Graphify recorded an external network/tooling blocker.
- `failed` when a source verification command fails or the checkpoint diff is
  dirty.

Do not return custom statuses such as `verification_failed`.

- [ ] **Step 8: Commit**

```bash
git add docs/operations/verification.md docs/operations/waygent.md skills/waygent/SKILL.md graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "docs(waygent): document closure review cost flow"
```

---

## Final Verification Checklist

After all tasks are complete, run:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:fixture-lab
bun run waygent:dogfood
bun run --cwd apps/console build
git diff --check
```

If any native kernel files changed during implementation, also run:

```bash
cd native/kernel && cargo fmt --all -- --check
cd native/kernel && cargo clippy --workspace --all-targets -- -D warnings
cd native/kernel && cargo test --workspace
```

## Plan Self-Review

Spec coverage:

- P0 closure-first hardening is covered by Tasks 1, 2, and 3.
- P1 review loop integration is covered by Tasks 1, 4, 5, and 6.
- P2 cost and adapter hygiene is covered by Tasks 7, 8, and 9.
- Integration fixtures and dogfood evidence are covered by Task 10.
- Operator docs, skill mappings, Graphify, and final verification are covered by Task 11.

Ordering:

- Contracts land first so all later tasks can compile against additive types.
- Projection fixes land before review lifecycle so the current blocker is accurate.
- Review policy lands before automatic review dispatch.
- Recovery, budget, and stale-run work land after core closure and review contracts.
- Integration fixtures land after all behavior exists.

Safety:

- Every task has explicit file claims.
- Every task has safe verification commands.
- No task applies patches outside Waygent apply authority.
- Stale cleanup only marks runtime state or removes abandoned worktrees after explicit command paths.
