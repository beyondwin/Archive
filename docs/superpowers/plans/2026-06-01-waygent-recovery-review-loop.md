# Waygent Recovery-to-Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Waygent classify recoverable failed work, preserve safe salvage evidence, route patch-bearing failures into repair and review, and explain the resulting blocker or next action from durable state.

**Architecture:** Implement the loop in narrow slices: contracts and read projections first, then a pure failure-evidence classifier, then salvage artifact writing, then orchestrator scheduling. The runtime remains the source of truth for repair, review, verification, checkpoint, completion audit, and apply readiness; provider output never becomes apply-ready without Waygent-owned evidence.

**Tech Stack:** Bun, TypeScript project references, `@waygent/contracts`, `@waygent/orchestrator`, `@waygent/lens-projectors`, `@waygent/lens-store`, fake-provider scenario fixtures, filesystem JSON/JSONL artifacts.

---

## Source Spec

- Design spec: `docs/superpowers/specs/2026-06-01-waygent-recovery-review-loop-design.md`
- Existing adjacent implementation:
  - `packages/contracts/src/types.ts`
  - `packages/contracts/src/schemas.ts`
  - `packages/orchestrator/src/recoveryExecutor.ts`
  - `packages/orchestrator/src/taskRecovery.ts`
  - `packages/orchestrator/src/orchestrator.ts`
  - `packages/orchestrator/src/reviewRunner.ts`
  - `packages/lens-projectors/src/operatorDecision.ts`
  - `packages/testkit/src/waygentScenarioHarness.ts`

## File Structure Map

- `packages/contracts/src/types.ts`: adds projection-only fields for recoverable evidence and precise non-apply-ready reason.
- `packages/contracts/src/schemas.ts`: validates the new additive operator decision fields.
- `packages/contracts/tests/contracts.test.ts`: locks the contract additions.
- `packages/orchestrator/src/failureEvidence.ts`: pure classifier for failure class, patch evidence, diff safety, repair budget, and recommended action.
- `packages/orchestrator/tests/failureEvidence.test.ts`: TDD coverage for classifier branches.
- `packages/orchestrator/src/salvageArtifacts.ts`: writes `waygent.salvage_result.v1`, updates artifact index, and records recovery refs.
- `packages/orchestrator/tests/salvageArtifacts.test.ts`: validates artifact writing and unsafe-patch behavior.
- `packages/orchestrator/src/orchestrator.ts`: calls classifier and salvage writer from the task failure branch before generic scheduler recovery.
- `packages/orchestrator/src/runCommands.ts`: lets `waygent repair --last` select recoverable patch evidence from salvage as well as completed worker results.
- `packages/lens-projectors/src/operatorDecision.ts`: exposes `recoverable_evidence`, `why_not_apply_ready`, and action hints.
- `packages/lens-projectors/tests/operatorDecision.test.ts`: asserts projection shape and primary blocker consistency.
- `packages/testkit/src/waygentScenarioHarness.ts`: adds scenario flags for malformed-output salvage and repaired verification flows.
- `tests/waygent-scenarios/malformed-output-salvaged-patch.json`: first required scenario fixture.
- `tests/waygent-scenarios/verification-failed-repair-reviewed.json`: second required scenario fixture.
- `docs/operations/waygent.md`: documents recovery-to-review operator behavior.
- `docs/operations/verification.md`: adds the focused gate for this loop.

---

### Task 1: Contracts for Recoverable Evidence Projection

```yaml waygent-task
id: task_1_recoverable_evidence_contracts
title: Contracts for recoverable evidence projection
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

Append these tests near the existing operator decision contract tests in `packages/contracts/tests/contracts.test.ts`:

```ts
test("validates operator recoverable evidence projection additions", () => {
  const decision = validOperatorDecisionFixture({
    recoverable_evidence: [
      {
        task_id: "task_a",
        failure_class: "malformed_result",
        kind: "recoverable_patch",
        patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
        salvage_ref: "artifacts/salvage/task_a/attempt_task_a_1.json",
        recommended_action: "salvage_then_review",
        evidence_refs: [
          "artifacts/provider/attempt_task_a_1.stdout.txt",
          "artifacts/worker/task_a/attempt_1_patch.diff"
        ]
      }
    ],
    why_not_apply_ready: {
      reason: "review_evidence_missing",
      missing_contracts: ["review_evidence"],
      evidence_refs: ["state:/tmp/run/state.json"]
    }
  });

  expect(validateContract("waygent.operator_decision.v1", decision).valid).toBe(true);
});

test("rejects malformed recoverable evidence projection additions", () => {
  const decision = validOperatorDecisionFixture({
    recoverable_evidence: [
      {
        task_id: "task_a",
        failure_class: "verification_failed",
        kind: "recoverable_patch",
        patch_ref: "",
        salvage_ref: null,
        recommended_action: "unknown_action",
        evidence_refs: []
      }
    ],
    why_not_apply_ready: {
      reason: "",
      missing_contracts: [],
      evidence_refs: []
    }
  });

  expect(validateContract("waygent.operator_decision.v1", decision).valid).toBe(false);
});
```

If `validOperatorDecisionFixture` is missing in the test file, add this helper at the bottom of `packages/contracts/tests/contracts.test.ts`:

```ts
function validOperatorDecisionFixture(overrides: Record<string, unknown> = {}) {
  return {
    schema: "waygent.operator_decision.v1",
    run_id: "run_review",
    generated_at: "2026-06-01T00:00:00.000Z",
    status_summary: {
      display_status: "blocked",
      runtime_status: "blocked",
      lifecycle_outcome: "blocked",
      current_phase: "recover",
      active_tasks: 0,
      completed_tasks: 1,
      blocked_tasks: 1,
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

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
```

Expected: FAIL because `OperatorDecisionProjection` and the JSON schema do not yet define `recoverable_evidence` or `why_not_apply_ready`.

- [ ] **Step 3: Add TypeScript projection types**

Modify `packages/contracts/src/types.ts` after `OperatorEvidencePacket`:

```ts
export type RecoverableEvidenceKind = "recoverable_patch" | "recoverable_worker_result";
export type RecoverableEvidenceAction = "dispatch_repair" | "salvage_then_review";

export interface OperatorRecoverableEvidence {
  task_id: string;
  failure_class: FailureClass | string;
  kind: RecoverableEvidenceKind;
  patch_ref: string | null;
  worker_result_ref?: string | null;
  salvage_ref: string | null;
  recommended_action: RecoverableEvidenceAction;
  evidence_refs: string[];
}

export interface OperatorWhyNotApplyReady {
  reason: string;
  missing_contracts: string[];
  evidence_refs: string[];
}
```

Then extend `OperatorDecisionProjection`:

```ts
export interface OperatorDecisionProjection {
  schema: "waygent.operator_decision.v1";
  run_id: string;
  generated_at: string;
  status_summary: OperatorStatusSummary;
  primary_blocker: OperatorBlocker | null;
  secondary_blockers: OperatorBlocker[];
  allowed_actions: OperatorAllowedAction[];
  blocked_actions: OperatorBlockedAction[];
  evidence_packet: OperatorEvidencePacket;
  ai_handoff: OperatorAiHandoff;
  confidence: OperatorDecisionConfidence;
  unknown_reasons: string[];
  intake_recovery?: OperatorIntakeRecoverySummary;
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
  recoverable_evidence?: OperatorRecoverableEvidence[];
  why_not_apply_ready?: OperatorWhyNotApplyReady | null;
  cost_summary?: CostSummaryProjection;
  stale_run_status?: StaleRunStatus;
  source_projection_refs: OperatorSourceProjectionRefs;
}
```

- [ ] **Step 4: Add schema definitions**

Modify `packages/contracts/src/schemas.ts` near `costSummaryProjectionSchema`:

```ts
const recoverableEvidenceSchema = {
  type: "object",
  additionalProperties: false,
  required: ["task_id", "failure_class", "kind", "patch_ref", "salvage_ref", "recommended_action", "evidence_refs"],
  properties: {
    task_id: { type: "string", pattern: idPattern },
    failure_class: { type: "string", minLength: 1 },
    kind: { enum: ["recoverable_patch", "recoverable_worker_result"] },
    patch_ref: { type: "string", minLength: 1, nullable: true },
    worker_result_ref: { type: "string", minLength: 1, nullable: true },
    salvage_ref: { type: "string", minLength: 1, nullable: true },
    recommended_action: { enum: ["dispatch_repair", "salvage_then_review"] },
    evidence_refs: { type: "array", minItems: 1, items: { type: "string", minLength: 1 } }
  }
} as const;

const whyNotApplyReadySchema = {
  type: "object",
  additionalProperties: false,
  nullable: true,
  required: ["reason", "missing_contracts", "evidence_refs"],
  properties: {
    reason: { type: "string", minLength: 1 },
    missing_contracts: { type: "array", minItems: 1, items: { type: "string", minLength: 1 } },
    evidence_refs: { type: "array", items: { type: "string", minLength: 1 } }
  }
} as const;
```

Then add these properties inside `operatorDecisionProjectionSchema.properties`:

```ts
    recoverable_evidence: {
      type: "array",
      items: recoverableEvidenceSchema
    },
    why_not_apply_ready: whyNotApplyReadySchema,
```

- [ ] **Step 5: Verify contracts pass**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/contracts/tests/contracts.test.ts
git commit -m "feat: add Waygent recoverable evidence contracts"
```

---

### Task 2: Failure Evidence Classifier

```yaml waygent-task
id: task_2_failure_evidence_classifier
title: Failure evidence classifier
dependencies: [task_1_recoverable_evidence_contracts]
file_claims:
  - path: packages/orchestrator/src/failureEvidence.ts
    mode: owned
  - path: packages/orchestrator/src/index.ts
    mode: owned
  - path: packages/orchestrator/tests/failureEvidence.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/failureEvidence.test.ts
```

**Files:**
- Create: `packages/orchestrator/src/failureEvidence.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Test: `packages/orchestrator/tests/failureEvidence.test.ts`

- [ ] **Step 1: Write failing classifier tests**

Create `packages/orchestrator/tests/failureEvidence.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import type { WorkerResult } from "@waygent/contracts";
import { classifyFailureEvidence } from "../src/failureEvidence";

const completedWorkerWithPatch: WorkerResult = {
  schema: "runway.worker_result.v1",
  task_id: "task_a",
  candidate_id: "candidate_task_a",
  status: "completed",
  changed_files: ["a.txt"],
  summary: "Worker changed a.txt",
  evidence: {
    patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
    patch_sha256: "a".repeat(64),
    patch_byte_length: 12
  }
};

describe("classifyFailureEvidence", () => {
  test("routes verification failure with patch evidence to repair", () => {
    expect(classifyFailureEvidence({
      task_id: "task_a",
      failure_class: "verification_failed",
      worker_result: completedWorkerWithPatch,
      provider_attempt_ref: "artifacts/provider/attempt_task_a_1.stdout.txt",
      repair_budget: { max_attempts: 2, current: 0 }
    })).toEqual({
      kind: "recoverable_patch",
      task_id: "task_a",
      failure_class: "verification_failed",
      patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
      changed_files: ["a.txt"],
      evidence_refs: [
        "artifacts/provider/attempt_task_a_1.stdout.txt",
        "artifacts/worker/task_a/attempt_1_patch.diff"
      ],
      recommended_action: "dispatch_repair"
    });
  });

  test("routes malformed result with safe captured diff to salvage then review", () => {
    expect(classifyFailureEvidence({
      task_id: "task_b",
      failure_class: "malformed_result",
      captured_patch_ref: "artifacts/worker/task_b/attempt_1_patch.diff",
      changed_files: ["b.txt"],
      provider_attempt_ref: "artifacts/provider/attempt_task_b_1.stdout.txt",
      diff_scope_safe: true,
      repair_budget: { max_attempts: 2, current: 0 }
    })).toMatchObject({
      kind: "recoverable_patch",
      task_id: "task_b",
      failure_class: "malformed_result",
      patch_ref: "artifacts/worker/task_b/attempt_1_patch.diff",
      changed_files: ["b.txt"],
      recommended_action: "salvage_then_review"
    });
  });

  test("blocks malformed result when captured diff is unsafe", () => {
    expect(classifyFailureEvidence({
      task_id: "task_b",
      failure_class: "malformed_result",
      captured_patch_ref: "artifacts/worker/task_b/attempt_1_patch.diff",
      changed_files: ["../escape.txt"],
      provider_attempt_ref: "artifacts/provider/attempt_task_b_1.stdout.txt",
      diff_scope_safe: false,
      repair_budget: { max_attempts: 2, current: 0 }
    })).toEqual({
      kind: "needs_operator_decision",
      task_id: "task_b",
      failure_class: "malformed_result",
      reason: "unsafe_patch_scope",
      evidence_refs: [
        "artifacts/provider/attempt_task_b_1.stdout.txt",
        "artifacts/worker/task_b/attempt_1_patch.diff"
      ]
    });
  });

  test("asks for operator decision when no recoverable patch exists", () => {
    expect(classifyFailureEvidence({
      task_id: "task_c",
      failure_class: "adapter_crashed",
      provider_attempt_ref: "artifacts/provider/attempt_task_c_1.stderr.txt",
      repair_budget: { max_attempts: 2, current: 0 }
    })).toEqual({
      kind: "needs_operator_decision",
      task_id: "task_c",
      failure_class: "adapter_crashed",
      reason: "missing_patch_evidence",
      evidence_refs: ["artifacts/provider/attempt_task_c_1.stderr.txt"]
    });
  });

  test("stops when repair budget is exhausted", () => {
    expect(classifyFailureEvidence({
      task_id: "task_a",
      failure_class: "verification_failed",
      worker_result: completedWorkerWithPatch,
      provider_attempt_ref: "artifacts/provider/attempt_task_a_1.stdout.txt",
      repair_budget: { max_attempts: 2, current: 2 }
    })).toEqual({
      kind: "terminal_unrecoverable",
      task_id: "task_a",
      failure_class: "verification_failed",
      reason: "repair_budget_exhausted",
      evidence_refs: [
        "artifacts/provider/attempt_task_a_1.stdout.txt",
        "artifacts/worker/task_a/attempt_1_patch.diff"
      ]
    });
  });
});
```

- [ ] **Step 2: Run the new test and confirm failure**

Run:

```bash
bun test packages/orchestrator/tests/failureEvidence.test.ts
```

Expected: FAIL because `packages/orchestrator/src/failureEvidence.ts` does not exist.

- [ ] **Step 3: Implement the classifier**

Create `packages/orchestrator/src/failureEvidence.ts`:

```ts
import type { FailureClass, WorkerResult } from "@waygent/contracts";

export type FailureEvidenceKind =
  | "recoverable_patch"
  | "recoverable_worker_result"
  | "needs_operator_decision"
  | "terminal_unrecoverable";

export interface RepairBudgetSnapshot {
  max_attempts: number;
  current: number;
}

export interface FailureEvidenceInput {
  task_id: string;
  failure_class: FailureClass | string;
  worker_result?: WorkerResult | null;
  provider_attempt_ref?: string | null;
  captured_patch_ref?: string | null;
  changed_files?: string[];
  diff_scope_safe?: boolean;
  repair_budget: RepairBudgetSnapshot;
}

export type FailureEvidenceDecision =
  | {
      kind: "recoverable_patch";
      task_id: string;
      failure_class: FailureClass | string;
      patch_ref: string;
      changed_files: string[];
      evidence_refs: string[];
      recommended_action: "dispatch_repair" | "salvage_then_review";
    }
  | {
      kind: "recoverable_worker_result";
      task_id: string;
      failure_class: FailureClass | string;
      worker_result_ref: string;
      evidence_refs: string[];
      recommended_action: "dispatch_repair";
    }
  | {
      kind: "needs_operator_decision";
      task_id: string;
      failure_class: FailureClass | string;
      reason: string;
      evidence_refs: string[];
    }
  | {
      kind: "terminal_unrecoverable";
      task_id: string;
      failure_class: FailureClass | string;
      reason: string;
      evidence_refs: string[];
    };

const SALVAGE_FAILURES = new Set(["malformed_result", "adapter_crashed", "timeout"]);

export function classifyFailureEvidence(input: FailureEvidenceInput): FailureEvidenceDecision {
  const patchRef = patchRefFromInput(input);
  const evidenceRefs = evidenceRefsFor(input, patchRef);

  if (input.repair_budget.current >= input.repair_budget.max_attempts && patchRef) {
    return {
      kind: "terminal_unrecoverable",
      task_id: input.task_id,
      failure_class: input.failure_class,
      reason: "repair_budget_exhausted",
      evidence_refs: evidenceRefs
    };
  }

  if (input.failure_class === "verification_failed") {
    if (input.worker_result?.status === "completed" && patchRef) {
      return {
        kind: "recoverable_patch",
        task_id: input.task_id,
        failure_class: input.failure_class,
        patch_ref: patchRef,
        changed_files: changedFilesFrom(input),
        evidence_refs: evidenceRefs,
        recommended_action: "dispatch_repair"
      };
    }
    return decisionRequired(input, "missing_patch_evidence", evidenceRefs);
  }

  if (SALVAGE_FAILURES.has(String(input.failure_class))) {
    if (!patchRef) return decisionRequired(input, "missing_patch_evidence", evidenceRefs);
    if (input.diff_scope_safe === false) return decisionRequired(input, "unsafe_patch_scope", evidenceRefs);
    return {
      kind: "recoverable_patch",
      task_id: input.task_id,
      failure_class: input.failure_class,
      patch_ref: patchRef,
      changed_files: changedFilesFrom(input),
      evidence_refs: evidenceRefs,
      recommended_action: "salvage_then_review"
    };
  }

  return decisionRequired(input, "unsupported_failure_class", evidenceRefs);
}

function patchRefFromInput(input: FailureEvidenceInput): string | null {
  if (typeof input.captured_patch_ref === "string" && input.captured_patch_ref.length > 0) return input.captured_patch_ref;
  const evidence = input.worker_result?.evidence;
  const patchRef = evidence && typeof evidence === "object" && !Array.isArray(evidence)
    ? (evidence as Record<string, unknown>).patch_ref
    : null;
  return typeof patchRef === "string" && patchRef.length > 0 ? patchRef : null;
}

function changedFilesFrom(input: FailureEvidenceInput): string[] {
  if (input.changed_files && input.changed_files.length > 0) return [...new Set(input.changed_files)];
  return [...new Set(input.worker_result?.changed_files ?? [])];
}

function evidenceRefsFor(input: FailureEvidenceInput, patchRef: string | null): string[] {
  return [
    input.provider_attempt_ref ?? null,
    patchRef
  ].filter((ref): ref is string => typeof ref === "string" && ref.length > 0);
}

function decisionRequired(
  input: FailureEvidenceInput,
  reason: string,
  evidence_refs: string[]
): Extract<FailureEvidenceDecision, { kind: "needs_operator_decision" }> {
  return {
    kind: "needs_operator_decision",
    task_id: input.task_id,
    failure_class: input.failure_class,
    reason,
    evidence_refs
  };
}
```

- [ ] **Step 4: Export the classifier**

Modify `packages/orchestrator/src/index.ts`:

```ts
export * from "./failureEvidence";
```

- [ ] **Step 5: Verify classifier tests pass**

Run:

```bash
bun test packages/orchestrator/tests/failureEvidence.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator/src/failureEvidence.ts packages/orchestrator/src/index.ts packages/orchestrator/tests/failureEvidence.test.ts
git commit -m "feat: classify Waygent recoverable failure evidence"
```

---

### Task 3: Salvage Artifact Writer

```yaml waygent-task
id: task_3_salvage_artifact_writer
title: Salvage artifact writer
dependencies: [task_2_failure_evidence_classifier]
file_claims:
  - path: packages/orchestrator/src/salvageArtifacts.ts
    mode: owned
  - path: packages/orchestrator/src/index.ts
    mode: owned
  - path: packages/orchestrator/tests/salvageArtifacts.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/salvageArtifacts.test.ts
```

**Files:**
- Create: `packages/orchestrator/src/salvageArtifacts.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Test: `packages/orchestrator/tests/salvageArtifacts.test.ts`

- [ ] **Step 1: Write failing salvage artifact tests**

Create `packages/orchestrator/tests/salvageArtifacts.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { recordSalvageArtifact } from "../src/salvageArtifacts";
import { baseV2State } from "./support/runStateFixture";

describe("recordSalvageArtifact", () => {
  test("writes salvage result and indexes it", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-salvage-artifact-"));
    const state = baseV2State({ root, run_id: "run_salvage" });
    const result = recordSalvageArtifact({
      state,
      task_id: "task_a",
      attempt_id: "attempt_task_a_1",
      status: "salvaged_patch",
      patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
      changed_files: ["a.txt"],
      reason: null,
      evidence_refs: ["artifacts/provider/attempt_task_a_1.stdout.txt"]
    });

    expect(result.artifact.path).toBe("artifacts/salvage/task_a/attempt_task_a_1.json");
    const written = JSON.parse(readFileSync(join(state.run_root, result.artifact.path), "utf8"));
    expect(written).toMatchObject({
      schema: "waygent.salvage_result.v1",
      task_id: "task_a",
      status: "salvaged_patch",
      patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff"
    });
    expect(result.nextState.artifact_index).toEqual(expect.arrayContaining([
      expect.objectContaining({
        ref: "artifacts/salvage/task_a/attempt_task_a_1.json",
        producer_phase: "decision",
        task_id: "task_a"
      })
    ]));
    expect(result.nextState.recovery).toEqual(expect.arrayContaining([
      expect.objectContaining({
        task_id: "task_a",
        action: "salvage_then_review",
        salvage_ref: "artifacts/salvage/task_a/attempt_task_a_1.json"
      })
    ]));
  });

  test("records unsafe patch without marking it repairable", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-salvage-unsafe-"));
    const state = baseV2State({ root, run_id: "run_salvage_unsafe" });
    const result = recordSalvageArtifact({
      state,
      task_id: "task_a",
      attempt_id: "attempt_task_a_1",
      status: "unsafe_patch",
      patch_ref: null,
      changed_files: ["../escape.txt"],
      reason: "unsafe_patch_scope",
      evidence_refs: ["artifacts/provider/attempt_task_a_1.stdout.txt"]
    });

    expect(result.nextState.recovery.at(-1)).toMatchObject({
      task_id: "task_a",
      action: "request_decision",
      result: "blocked",
      reason: "unsafe_patch_scope"
    });
  });
});
```

- [ ] **Step 2: Run the new test and confirm failure**

Run:

```bash
bun test packages/orchestrator/tests/salvageArtifacts.test.ts
```

Expected: FAIL because `salvageArtifacts.ts` does not exist.

- [ ] **Step 3: Implement the salvage writer**

Create `packages/orchestrator/src/salvageArtifacts.ts`:

```ts
import type { ArtifactReference, SalvageResult, WaygentRunStateV2 } from "@waygent/contracts";
import { writeArtifact } from "@waygent/lens-store";
import { artifactIndexEntry, mergeArtifactIndex } from "./artifactIndex";

export interface RecordSalvageArtifactInput {
  state: WaygentRunStateV2;
  task_id: string;
  attempt_id: string;
  status: SalvageResult["status"];
  patch_ref: string | null;
  changed_files: string[];
  reason: string | null;
  evidence_refs: string[];
}

export interface RecordSalvageArtifactResult {
  nextState: WaygentRunStateV2;
  artifact: ArtifactReference;
  salvage: SalvageResult;
}

export function recordSalvageArtifact(input: RecordSalvageArtifactInput): RecordSalvageArtifactResult {
  const salvage: SalvageResult = {
    schema: "waygent.salvage_result.v1",
    task_id: input.task_id,
    attempt_id: input.attempt_id,
    status: input.status,
    patch_ref: input.patch_ref,
    changed_files: [...new Set(input.changed_files)],
    reason: input.reason,
    evidence_refs: [...new Set(input.evidence_refs)]
  };
  const artifact = writeArtifact(
    input.state.run_root,
    `salvage/${input.task_id}/${input.attempt_id}.json`,
    `${JSON.stringify(salvage, null, 2)}\n`,
    "application/json"
  );
  const blocked = input.status !== "salvaged_patch";
  const nextState: WaygentRunStateV2 = {
    ...input.state,
    artifact_index: mergeArtifactIndex(input.state.artifact_index, [
      artifactIndexEntry({ artifact, producer_phase: "decision", task_id: input.task_id })
    ]),
    recovery: [
      ...input.state.recovery,
      {
        task_id: input.task_id,
        failure_class: input.reason ?? "recoverable_patch",
        action: blocked ? "request_decision" : "salvage_then_review",
        automatic: !blocked,
        result: blocked ? "blocked" : "scheduled",
        reason: input.reason,
        salvage_ref: artifact.path,
        patch_ref: input.patch_ref,
        evidence_refs: salvage.evidence_refs
      }
    ]
  };
  return { nextState, artifact, salvage };
}
```

- [ ] **Step 4: Export the salvage writer**

Modify `packages/orchestrator/src/index.ts`:

```ts
export * from "./salvageArtifacts";
```

- [ ] **Step 5: Verify salvage tests pass**

Run:

```bash
bun test packages/orchestrator/tests/salvageArtifacts.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator/src/salvageArtifacts.ts packages/orchestrator/src/index.ts packages/orchestrator/tests/salvageArtifacts.test.ts
git commit -m "feat: record Waygent salvage artifacts"
```

---

### Task 4: Operator Projection for Recoverable Evidence

```yaml waygent-task
id: task_4_operator_projection_recoverable_evidence
title: Operator projection for recoverable evidence
dependencies: [task_1_recoverable_evidence_contracts, task_2_failure_evidence_classifier]
file_claims:
  - path: packages/lens-projectors/src/operatorDecision.ts
    mode: owned
  - path: packages/lens-projectors/tests/operatorDecision.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/lens-projectors/tests/operatorDecision.test.ts
```

**Files:**
- Modify: `packages/lens-projectors/src/operatorDecision.ts`
- Test: `packages/lens-projectors/tests/operatorDecision.test.ts`

- [ ] **Step 1: Add failing projection tests**

Append this test inside the existing `projectOperatorDecisionFromState` describe block in `packages/lens-projectors/tests/operatorDecision.test.ts`:

```ts
test("surfaces salvage recovery as recoverable evidence and review blocker", () => {
  const state = makeState({
    status: "blocked",
    lifecycle_outcome: "blocked",
    current_phase: "review",
    tasks: {
      task_a: task("task_a", {
        status: "verified",
        review_required: true,
        review_status: "pending",
        latest_failure_class: null
      })
    },
    recovery: [
      {
        task_id: "task_a",
        failure_class: "malformed_result",
        action: "salvage_then_review",
        result: "scheduled",
        salvage_ref: "artifacts/salvage/task_a/attempt_task_a_1.json",
        patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
        evidence_refs: ["artifacts/provider/attempt_task_a_1.stdout.txt"]
      }
    ],
    completion_audit: {
      status: "failed",
      residual_risk: ["review_evidence:recovery_attempted"]
    },
    apply: { status: "blocked", reason: "review_evidence_missing" }
  });

  const projection = projectOperatorDecisionFromState({ state, events: [] });

  expect(projection.primary_blocker?.code).toBe("review_evidence_missing");
  expect(projection.recoverable_evidence).toEqual([
    expect.objectContaining({
      task_id: "task_a",
      failure_class: "malformed_result",
      kind: "recoverable_patch",
      patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
      salvage_ref: "artifacts/salvage/task_a/attempt_task_a_1.json",
      recommended_action: "salvage_then_review"
    })
  ]);
  expect(projection.why_not_apply_ready).toEqual({
    reason: "review_evidence_missing",
    missing_contracts: ["review_evidence"],
    evidence_refs: ["state:/tmp/run_demo/state.json"]
  });
  expect(projection.allowed_actions.map((action) => action.id)).toContain("run_review");
});
```

- [ ] **Step 2: Run the projection test and confirm failure**

Run:

```bash
bun test packages/lens-projectors/tests/operatorDecision.test.ts
```

Expected: FAIL because the projection does not fill `recoverable_evidence` or `why_not_apply_ready`.

- [ ] **Step 3: Add projection helpers**

Modify `packages/lens-projectors/src/operatorDecision.ts` near `recoveredFailuresFromState`:

```ts
function recoverableEvidenceFromState(state: WaygentRunStateV2): NonNullable<OperatorDecisionProjection["recoverable_evidence"]> {
  return (state.recovery ?? [])
    .filter((record) => record && typeof record === "object")
    .map((record) => record as Record<string, unknown>)
    .filter((record) => record.action === "salvage_then_review" || record.action === "dispatch_repair")
    .map((record) => {
      const taskId = typeof record.task_id === "string" ? record.task_id : "";
      const patchRef = typeof record.patch_ref === "string" ? record.patch_ref : null;
      const workerResultRef = typeof record.worker_result_ref === "string" ? record.worker_result_ref : null;
      const salvageRef = typeof record.salvage_ref === "string" ? record.salvage_ref : null;
      const evidenceRefs = Array.isArray(record.evidence_refs)
        ? record.evidence_refs.filter((ref): ref is string => typeof ref === "string" && ref.length > 0)
        : [];
      return {
        task_id: taskId,
        failure_class: typeof record.failure_class === "string" ? record.failure_class : "unknown",
        kind: patchRef ? "recoverable_patch" as const : "recoverable_worker_result" as const,
        patch_ref: patchRef,
        worker_result_ref: workerResultRef,
        salvage_ref: salvageRef,
        recommended_action: record.action === "dispatch_repair" ? "dispatch_repair" as const : "salvage_then_review" as const,
        evidence_refs: unique([...evidenceRefs, ...(patchRef ? [patchRef] : []), ...(salvageRef ? [salvageRef] : [])])
      };
    })
    .filter((item) => item.task_id.length > 0 && item.evidence_refs.length > 0);
}

function whyNotApplyReadyFromState(
  state: WaygentRunStateV2,
  applyReadiness: ApplyReadinessProjection
): OperatorDecisionProjection["why_not_apply_ready"] {
  if (applyReadiness.status === "ready") return null;
  const reason = applyReadiness.reason ?? state.apply.reason ?? applyReadiness.status;
  const missing_contracts = missingApplyContracts(reason);
  return {
    reason,
    missing_contracts,
    evidence_refs: [stateRef(state)]
  };
}

function missingApplyContracts(reason: string): string[] {
  if (reason === "review_evidence_missing") return ["review_evidence"];
  if (reason === "combined_apply_evidence_missing") return ["combined_apply_evidence"];
  if (reason === "checkpoint_not_apply_ready" || reason === "missing_checkpoint") return ["checkpoint_evidence"];
  if (reason === "state_reconciliation_failed" || reason === "state_drift") return ["state_reconciliation"];
  if (reason === "dirty_source_checkout") return ["clean_source_checkout"];
  if (reason === "verification_failed") return ["verification_evidence"];
  return [reason];
}
```

- [ ] **Step 4: Wire the new fields into the projection**

In `projectOperatorDecisionFromState`, find the returned object for the state-backed path and add:

```ts
    recoverable_evidence: recoverableEvidenceFromState(state),
    why_not_apply_ready: whyNotApplyReadyFromState(state, applyReadiness),
```

The object should already include `recovered_failures`, `cost_summary`, and `source_projection_refs`; keep those fields unchanged.

- [ ] **Step 5: Verify projection tests pass**

Run:

```bash
bun test packages/lens-projectors/tests/operatorDecision.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/lens-projectors/src/operatorDecision.ts packages/lens-projectors/tests/operatorDecision.test.ts
git commit -m "feat: project Waygent recoverable evidence"
```

---

### Task 5: Orchestrator Salvage and Repair Wiring

```yaml waygent-task
id: task_5_orchestrator_salvage_repair_wiring
title: Orchestrator salvage and repair wiring
dependencies: [task_2_failure_evidence_classifier, task_3_salvage_artifact_writer, task_4_operator_projection_recoverable_evidence]
file_claims:
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/src/runCommands.ts
    mode: owned
  - path: packages/orchestrator/tests/repairAction.test.ts
    mode: owned
  - path: packages/orchestrator/tests/orchestratorRun.test.ts
    mode: owned
risk: high
verify_isolation: "isolated"
verify:
  - bun test packages/orchestrator/tests/repairAction.test.ts packages/orchestrator/tests/orchestratorRun.test.ts
```

**Files:**
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Test: `packages/orchestrator/tests/repairAction.test.ts`
- Test: `packages/orchestrator/tests/orchestratorRun.test.ts`

- [ ] **Step 1: Add repair selection tests for salvage records**

Append to `packages/orchestrator/tests/repairAction.test.ts`:

```ts
import { repairCandidateFromRecoveryRecord } from "../src/runCommands";

test("builds manual repair candidate from salvage recovery record", () => {
  expect(repairCandidateFromRecoveryRecord({
    task_id: "task_a",
    failure_class: "malformed_result",
    action: "salvage_then_review",
    result: "scheduled",
    patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
    salvage_ref: "artifacts/salvage/task_a/attempt_task_a_1.json",
    evidence_refs: ["artifacts/provider/attempt_task_a_1.stdout.txt"]
  })).toEqual({
    task_id: "task_a",
    failure_class: "malformed_result",
    patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
    salvage_ref: "artifacts/salvage/task_a/attempt_task_a_1.json",
    evidence_refs: [
      "artifacts/provider/attempt_task_a_1.stdout.txt",
      "artifacts/worker/task_a/attempt_1_patch.diff",
      "artifacts/salvage/task_a/attempt_task_a_1.json"
    ]
  });
});
```

- [ ] **Step 2: Run the focused test and confirm failure**

Run:

```bash
bun test packages/orchestrator/tests/repairAction.test.ts
```

Expected: FAIL because `repairCandidateFromRecoveryRecord` is not exported.

- [ ] **Step 3: Add a repair candidate helper**

Modify `packages/orchestrator/src/runCommands.ts` near `readWorkerResultForTask`:

```ts
export interface SalvageRepairCandidate {
  task_id: string;
  failure_class: string;
  patch_ref: string;
  salvage_ref: string | null;
  evidence_refs: string[];
}

export function repairCandidateFromRecoveryRecord(record: Record<string, unknown>): SalvageRepairCandidate | null {
  if (record.action !== "salvage_then_review" && record.action !== "dispatch_repair") return null;
  const taskId = typeof record.task_id === "string" ? record.task_id : null;
  const patchRef = typeof record.patch_ref === "string" ? record.patch_ref : null;
  if (!taskId || !patchRef) return null;
  const salvageRef = typeof record.salvage_ref === "string" ? record.salvage_ref : null;
  const evidenceRefs = Array.isArray(record.evidence_refs)
    ? record.evidence_refs.filter((ref): ref is string => typeof ref === "string" && ref.length > 0)
    : [];
  return {
    task_id: taskId,
    failure_class: typeof record.failure_class === "string" ? record.failure_class : "unknown",
    patch_ref: patchRef,
    salvage_ref: salvageRef,
    evidence_refs: [...new Set([...evidenceRefs, patchRef, ...(salvageRef ? [salvageRef] : [])])]
  };
}
```

- [ ] **Step 4: Extend `repairRun` candidate discovery**

In `repairRun`, after the existing worker-result candidate loop, add a salvage candidate list:

```ts
  const salvageCandidates = v2.recovery
    .map((record) => repairCandidateFromRecoveryRecord(record as Record<string, unknown>))
    .filter((candidate): candidate is SalvageRepairCandidate => candidate !== null)
    .filter((candidate) => !options.task || candidate.task_id === options.task);
```

Then, before returning `no_repairable_task`, support dry-run repair packets from salvage evidence:

```ts
  if (candidates.length === 0 && salvageCandidates.length > 0) {
    if (!options.task && salvageCandidates.length > 1) {
      return { command: "repair", run_id: runId, status: "blocked", reason: "ambiguous_task_select_via_flag" };
    }
    const salvage = salvageCandidates.at(-1)!;
    const task = v2.tasks[salvage.task_id];
    if (!task) return { command: "repair", run_id: runId, status: "blocked", reason: "no_repairable_task" };
    const packet = buildRepairPacket({
      task_id: salvage.task_id,
      attempt_id: `attempt_${salvage.task_id}_repair_salvage_manual`,
      prior_worker_result: {
        schema: "runway.worker_result.v1",
        task_id: salvage.task_id,
        candidate_id: `candidate_${salvage.task_id}_salvaged`,
        status: "completed",
        changed_files: task.file_claims.filter((claim) => claim.mode !== "read_only").map((claim) => claim.path),
        summary: `Repair from salvaged patch ${salvage.patch_ref}`,
        evidence: {
          patch_ref: salvage.patch_ref,
          salvage_ref: salvage.salvage_ref,
          evidence_refs: salvage.evidence_refs
        }
      },
      verifications: []
    });
    if (options.dry_run) {
      return { command: "repair", run_id: runId, task_id: salvage.task_id, status: "dry_run", packet };
    }
    return {
      command: "repair",
      run_id: runId,
      task_id: salvage.task_id,
      status: "blocked",
      reason: "salvage_repair_requires_runtime_resume"
    };
  }
```

This keeps manual repair safe: it can produce a bounded packet, but applying the prior patch and dispatching a provider still belongs to the runtime resume path.

- [ ] **Step 5: Add orchestrator salvage scheduling test**

Append this test to `packages/orchestrator/tests/orchestratorRun.test.ts`:

```ts
test("records salvage evidence for malformed provider output with captured patch", async () => {
  const workspace = initSourceCheckout("waygent-salvage-malformed-source-");
  const root = mkdtempSync(join(tmpdir(), "waygent-salvage-malformed-root-"));
  const script = join(workspace, "malformed-provider.mjs");
  writeFileSync(script, [
    "import { writeFileSync } from 'node:fs';",
    "writeFileSync('salvage.txt', 'salvaged\\n');",
    "process.stdout.write('{not json');"
  ].join("\n"));

  const result = await runWaygent({
    root,
    workspace,
    run_id: "run_salvage_malformed",
    plan: "```yaml waygent-task\nid: task_salvage\ntitle: Salvage malformed provider\ndependencies: []\nfile_claims:\n  - path: salvage.txt\n    mode: owned\nrisk: low\nverify:\n  - test -f salvage.txt\n```",
    profile: { provider: "codex", execution_mode: "multi-agent" },
    provider_processes: {
      codex: {
        executable: process.execPath,
        args: [script]
      }
    }
  });

  const state = readRunStateV2(root, "run_salvage_malformed");
  expect(result.events.map((event) => event.event_type)).toContain("runway.patch_salvaged");
  expect(state.recovery).toEqual(expect.arrayContaining([
    expect.objectContaining({
      task_id: "task_salvage",
      action: "salvage_then_review",
      result: "scheduled",
      salvage_ref: "artifacts/salvage/task_salvage/attempt_task_salvage_1.json"
    })
  ]));
  expect(state.apply.status).toBe("blocked");
  expect(state.completion_audit?.status).toBe("failed");
});
```

- [ ] **Step 6: Run the orchestrator test and confirm failure**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorRun.test.ts
```

Expected: FAIL because the orchestrator does not yet record salvage artifacts or emit `runway.patch_salvaged`.

- [ ] **Step 7: Wire classifier and salvage writer into task failure handling**

Modify imports in `packages/orchestrator/src/orchestrator.ts`:

```ts
import { classifyFailureEvidence } from "./failureEvidence";
import { recordSalvageArtifact } from "./salvageArtifacts";
```

In the task failure branch immediately before `recordTaskRecovery(context, { ... })`, add:

```ts
        const capturedPatchRef = typeof priorWorker.evidence?.patch_ref === "string"
          ? priorWorker.evidence.patch_ref
          : null;
        const failureDecision = classifyFailureEvidence({
          task_id: waveResult.task_id,
          failure_class: failureClass,
          worker_result: priorWorker,
          provider_attempt_ref: waveResult.result.provider_attempt.stdout_ref,
          captured_patch_ref: capturedPatchRef,
          changed_files: priorWorker.changed_files,
          diff_scope_safe: failureClass !== "diff_scope_failed",
          repair_budget: repairBudget
        });
        if (failureDecision.kind === "recoverable_patch" && failureDecision.recommended_action === "salvage_then_review") {
          const salvage = recordSalvageArtifact({
            state: context.state,
            task_id: failureDecision.task_id,
            attempt_id: waveResult.result.provider_attempt.attempt_id,
            status: "salvaged_patch",
            patch_ref: failureDecision.patch_ref,
            changed_files: failureDecision.changed_files,
            reason: null,
            evidence_refs: failureDecision.evidence_refs
          });
          context.mutateState((state) => {
            Object.assign(state, salvage.nextState);
            const stateTask = state.tasks[failureDecision.task_id];
            if (stateTask) {
              stateTask.status = "review_pending";
              stateTask.review_required = true;
              stateTask.review_status = "pending";
              stateTask.latest_failure_class = null;
            }
            state.current_phase = "review";
            state.status = "blocked";
            state.lifecycle_outcome = "blocked";
            state.apply = { status: "blocked", reason: "review_evidence_missing" };
          });
          context.appendEvent((sequence) => buildRunEvent({
            run_id: runId,
            sequence,
            event_type: "runway.patch_salvaged",
            phase: "recover",
            outcome: "success",
            summary: "Waygent recorded a salvage candidate patch that requires review.",
            payload: {
              task_id: failureDecision.task_id,
              failure_class: failureDecision.failure_class,
              salvage_ref: salvage.artifact.path,
              patch_ref: failureDecision.patch_ref,
              changed_files: failureDecision.changed_files
            },
            trust_impact: "requires_review"
          }));
          context.flushState();
          continue;
        }
```

If TypeScript reports that `Object.assign(state, salvage.nextState)` is too broad for the mutable state helper, replace that line with explicit assignments:

```ts
            state.artifact_index = salvage.nextState.artifact_index;
            state.recovery = salvage.nextState.recovery;
```

- [ ] **Step 8: Verify focused tests pass**

Run:

```bash
bun test packages/orchestrator/tests/repairAction.test.ts packages/orchestrator/tests/orchestratorRun.test.ts
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add packages/orchestrator/src/orchestrator.ts packages/orchestrator/src/runCommands.ts packages/orchestrator/tests/repairAction.test.ts packages/orchestrator/tests/orchestratorRun.test.ts
git commit -m "feat: route Waygent salvage evidence into review"
```

---

### Task 6: Scenario Fixtures, Docs, and Verification Gate

```yaml waygent-task
id: task_6_recovery_review_scenarios_docs
title: Recovery-to-review scenarios and docs
dependencies: [task_4_operator_projection_recoverable_evidence, task_5_orchestrator_salvage_repair_wiring]
file_claims:
  - path: packages/testkit/src/waygentScenarioHarness.ts
    mode: owned
  - path: tests/waygent-scenarios/malformed-output-salvaged-patch.json
    mode: owned
  - path: tests/waygent-scenarios/verification-failed-repair-reviewed.json
    mode: owned
  - path: docs/operations/waygent.md
    mode: owned
  - path: docs/operations/verification.md
    mode: owned
  - path: graphify-out/GRAPH_REPORT.md
    mode: owned
  - path: graphify-out/graph.json
    mode: owned
risk: medium
verify_isolation: "isolated"
verify:
  - bun run waygent:scenarios
  - bun run waygent:fixture-lab
  - bun run waygent:dogfood
  - git diff --check
```

**Files:**
- Modify: `packages/testkit/src/waygentScenarioHarness.ts`
- Create: `tests/waygent-scenarios/malformed-output-salvaged-patch.json`
- Create: `tests/waygent-scenarios/verification-failed-repair-reviewed.json`
- Modify: `docs/operations/waygent.md`
- Modify: `docs/operations/verification.md`
- Modify after Graphify refresh: `graphify-out/GRAPH_REPORT.md`
- Modify after Graphify refresh: `graphify-out/graph.json`

- [ ] **Step 1: Extend scenario harness flags**

Modify `packages/testkit/src/waygentScenarioHarness.ts`:

```ts
export interface WaygentScenario {
  id: string;
  title: string;
  provider_fixture: WaygentScenarioProviderFixture;
  source_dirty_before_apply: boolean;
  force_missing_checkpoint: boolean;
  checkpoint_dry_run_conflict?: boolean;
  stale_verification_recovered?: boolean;
  review_evidence_missing?: boolean;
  review_evidence_passed?: boolean;
  budget_paused?: boolean;
  salvaged_patch_needs_review?: boolean;
  malformed_output_salvaged_patch?: boolean;
  verification_failed_repair_reviewed?: boolean;
  plan: string;
  expected: WaygentScenarioExpectedReplay;
}
```

Add the two new flags to the validation loop in `loadWaygentScenario`:

```ts
    "malformed_output_salvaged_patch",
    "verification_failed_repair_reviewed"
```

Add the two new flags to the early return guard in `applyScenarioStateFaults`:

```ts
    && !scenario.malformed_output_salvaged_patch
    && !scenario.verification_failed_repair_reviewed
```

Add state fault handling before returning `next`:

```ts
  if (scenario.malformed_output_salvaged_patch && taskId) {
    addRecoveredFailure(next, taskId, "malformed_result", [`salvage:${taskId}`]);
    markReviewEvidenceMissing(next);
    next.recovery = [
      ...next.recovery,
      {
        task_id: taskId,
        failure_class: "malformed_result",
        action: "salvage_then_review",
        result: "scheduled",
        salvage_ref: `artifacts/salvage/${taskId}/attempt_${taskId}_1.json`,
        patch_ref: `artifacts/worker/${taskId}/attempt_1_patch.diff`,
        evidence_refs: [`artifacts/provider/attempt_${taskId}_1.stdout.txt`]
      }
    ];
  }
  if (scenario.verification_failed_repair_reviewed && taskId) {
    addRecoveredFailure(next, taskId, "verification_failed", [`repair:${taskId}`]);
    addPassedReviewEvidence(next, taskId);
    const task = next.tasks[taskId];
    if (task) {
      task.status = "verified";
      task.latest_failure_class = null;
      task.review_required = true;
      task.review_status = "passed";
    }
    next.status = "completed";
    next.lifecycle_outcome = "finished";
    next.current_phase = "complete";
    next.apply = { status: "not_ready" };
    next.completion_audit = {
      ...(next.completion_audit ?? {}),
      status: "passed",
      residual_risk: []
    };
  }
```

- [ ] **Step 2: Add malformed-output salvage scenario**

Create `tests/waygent-scenarios/malformed-output-salvaged-patch.json`:

```json
{
  "id": "malformed-output-salvaged-patch",
  "title": "Malformed output with salvaged patch requires review",
  "provider_fixture": "fake-success",
  "source_dirty_before_apply": false,
  "force_missing_checkpoint": false,
  "malformed_output_salvaged_patch": true,
  "plan": "```yaml waygent-task\nid: task_malformed_salvage\ntitle: Malformed output salvage task\ndependencies: []\nfile_claims:\n  - path: malformed-salvage.txt\n    mode: owned\nrisk: low\nverify:\n  - printf malformed-salvage\n```",
  "expected": {
    "run_status": "failed",
    "apply_status": "blocked",
    "trust_status": "needs_review",
    "apply_reason": "review_evidence_missing",
    "operator_primary_blocker": "review_evidence_missing",
    "operator_allowed_actions": ["run_review"],
    "safe_wave": ["task_malformed_salvage"],
    "event_types_must_include": [
      "platform.run_started",
      "runway.worker_result",
      "runway.verification_result",
      "lens.trust_report_updated"
    ],
    "blockers": ["review_evidence_missing"],
    "combined_patch_ref": "artifacts/checkpoints/apply/scenario_malformed-output-salvaged-patch.patch"
  }
}
```

- [ ] **Step 3: Add verification-failed repair-reviewed scenario**

Create `tests/waygent-scenarios/verification-failed-repair-reviewed.json`:

```json
{
  "id": "verification-failed-repair-reviewed",
  "title": "Verification failure recovered by repair and review",
  "provider_fixture": "fake-success",
  "source_dirty_before_apply": false,
  "force_missing_checkpoint": false,
  "verification_failed_repair_reviewed": true,
  "plan": "```yaml waygent-task\nid: task_repair_reviewed\ntitle: Verification failure repair reviewed task\ndependencies: []\nfile_claims:\n  - path: repair-reviewed.txt\n    mode: owned\nrisk: low\nverify:\n  - printf repair-reviewed\n```",
  "expected": {
    "run_status": "trusted",
    "apply_status": "ready",
    "trust_status": "trusted",
    "apply_reason": "ready",
    "operator_primary_blocker": null,
    "operator_allowed_actions": ["apply_run"],
    "safe_wave": ["task_repair_reviewed"],
    "event_types_must_include": [
      "platform.run_started",
      "runway.worker_result",
      "runway.verification_result",
      "runway.checkpoint_created",
      "runway.apply_dry_run_result",
      "lens.trust_report_updated"
    ],
    "combined_patch_ref": "artifacts/checkpoints/apply/scenario_verification-failed-repair-reviewed.patch"
  }
}
```

- [ ] **Step 4: Run scenarios and adjust only expected deterministic counts if needed**

Run:

```bash
bun run waygent:scenarios
```

Expected: PASS. If the failure is only `total_events` drift, prefer `event_types_must_include` over pinning exact counts for these two new fixtures.

- [ ] **Step 5: Document operator behavior**

Add this section to `docs/operations/waygent.md` under "Recovery Actions":

```md
### Recovery-to-Review Loop

Patch-bearing failures are recovered before full worker retry when the evidence
is safe to inspect. `verification_failed` with a completed worker result and a
patch ref routes to focused repair. `malformed_result`, `adapter_crashed`, and
`timeout` with a bounded captured diff record `waygent.salvage_result.v1` and
block as review-required evidence until review and verification pass.

Salvage is not success. A salvaged patch can start repair or review, but it
does not create an apply-ready checkpoint by itself. Apply readiness still
requires review evidence when policy requires it, verification evidence,
checkpoint manifests, dry-run evidence, combined apply evidence, reconciliation,
and a clean source checkout.
```

- [ ] **Step 6: Document verification gate**

Add this subsection to `docs/operations/verification.md` after the "Closure, Review, and Cost Reliability Gate":

~~~md
## Recovery-to-Review Gate

Use this gate after changes to failure evidence classification, salvage
artifacts, repair scheduling, review-required recovered work, or operator
projection fields:

```bash
bun test packages/orchestrator/tests/failureEvidence.test.ts packages/orchestrator/tests/salvageArtifacts.test.ts
bun test packages/lens-projectors/tests/operatorDecision.test.ts
bun run waygent:scenarios
bun run waygent:fixture-lab
bun run waygent:dogfood
git diff --check
```

Expected behavior:

- patch-bearing verification failures route to focused repair before full retry;
- malformed provider output with a safe captured diff records salvage evidence;
- salvaged patches block as review-required until review evidence exists;
- recovered and reviewed verification failures can become apply-ready;
- `waygent explain`, API, and console projections read the same operator
  decision fields.
~~~

- [ ] **Step 7: Refresh Graphify**

Run:

```bash
graphify update .
```

Expected: `graphify-out/GRAPH_REPORT.md` shows the current `git rev-parse HEAD` prefix in `Built from commit`.

- [ ] **Step 8: Run the final focused gate**

Run:

```bash
bun test packages/orchestrator/tests/failureEvidence.test.ts packages/orchestrator/tests/salvageArtifacts.test.ts
bun test packages/lens-projectors/tests/operatorDecision.test.ts
bun run waygent:scenarios
bun run waygent:fixture-lab
bun run waygent:dogfood
git diff --check
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add packages/testkit/src/waygentScenarioHarness.ts tests/waygent-scenarios/malformed-output-salvaged-patch.json tests/waygent-scenarios/verification-failed-repair-reviewed.json docs/operations/waygent.md docs/operations/verification.md graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "test: cover Waygent recovery review scenarios"
```

---

## Final Verification

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

Expected: all commands pass. If `apps/console` build changes generated local `dist/` output, leave ignored build output unstaged.

## Review Checklist

- Salvaged patches never become apply-ready without review and verification.
- `review_evidence_missing` remains the precise blocker for recovered tasks lacking required review evidence.
- `waygent repair --dry-run` can inspect salvage evidence without mutating the source checkout.
- Scenario fixtures avoid exact event counts unless count stability is part of the behavior.
- Graphify output is refreshed after documentation and structure changes.
