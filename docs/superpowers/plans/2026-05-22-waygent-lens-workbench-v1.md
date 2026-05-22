# Waygent Lens Workbench v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first product-grade Waygent Lens Workbench slice: a shared operator decision projection with API, CLI, and Console parity for run status, blockers, safe actions, evidence, and AI repair handoff.

**Architecture:** Add `waygent.operator_decision.v1` as a shared contract, compute it in `packages/lens-projectors` from `waygent.run_state.v2` plus existing Lens projections, expose it through the API and CLI, then reshape the Console around a Run Board, Outcome Strip, Operator Timeline, and Decision/Evidence Rail. Waygent runtime remains the authority for resume, recovery, verification, and apply; Lens only projects evidence and guidance.

**Tech Stack:** TypeScript, Bun test runner, React 19, Vite, AJV contract validation, existing Waygent workspace packages.

---

## Source Spec

Implement from:

- `docs/superpowers/specs/2026-05-22-waygent-lens-workbench-v1-design.md`
- `AGENTS.md`
- `PLANS.md`

Durable constraints:

- Do not recreate or route active work through legacy Python `components/agentlens/`.
- Do not revive KWS CPE or KWS CME as active routing.
- Keep active event contracts under `agentlens.event.v3` with `platform.*`, `runway.*`, `kernel.*`, and `lens.*`.
- `waygent.run_state.v2` remains the runtime source of truth when present.
- Apply is allowed only by existing apply readiness and runtime revalidation.
- AI repair handoff is bounded, read-only, and non-authoritative.

## File Structure

### Create

- `packages/lens-projectors/src/operatorDecision.ts`
  - Pure projector for `waygent.operator_decision.v1`.
- `packages/lens-projectors/tests/operatorDecision.test.ts`
  - Fixture-driven projector tests for ready, blocked, missing-state, and incomplete-evidence cases.

### Modify

- `packages/contracts/src/types.ts`
  - Add shared operator decision, blocker, action, evidence, handoff, and timeline row types.
- `packages/contracts/src/schemas.ts`
  - Add AJV schema for `waygent.operator_decision.v1`.
- `packages/contracts/tests/contracts.test.ts`
  - Validate canonical operator decision payload and rejection of extra properties.
- `packages/lens-projectors/src/index.ts`
  - Export the operator decision projector.
- `packages/orchestrator/src/runCommands.ts`
  - Include operator decision in `inspectRun()` and make `explainRun()` read the same primary blocker/action summary.
- `apps/api/src/server.ts`
  - Include operator decision in real run list summaries and run detail.
- `apps/api/tests/api.test.ts`
  - Assert API exposes operator decision and matches console/inspect facts.
- `apps/cli/tests/cli.test.ts`
  - Assert `inspect` and `explain` expose the same operator decision primary blocker and action set.
- `apps/console/src/uiModel.ts`
  - Add Workbench data model fields and typed operator timeline rows.
- `apps/console/src/uiModel.test.ts`
  - Assert run urgency ordering, outcome strip values, disabled apply reason, AI handoff, and raw fallback reachability.
- `apps/console/src/App.tsx`
  - Render Run Board, Sticky Outcome Strip, Operator Timeline, and Decision/Evidence Rail.
- `apps/console/src/styles.css`
  - Product-grade Workbench layout, responsive narrow layout, stable row dimensions, and disabled-action affordances.
- `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`
  - Refresh after code/doc structure changes with `graphify update .`.

### Do Not Touch

- `components/agentlens/`
- `.agentlens/`
- `.superpowers/`
- `.claude/`
- `.codex-orchestrator/`
- `.orchestrator/`
- `node_modules/`

## Execution Order

Sequential path:

1. Task 1: Contract.
2. Task 2: Pure projector.
3. Task 3: API and CLI parity.
4. Task 4: Console UI model.
5. Task 5: Console product surface and browser QA.
6. Task 6: Full verification, Graphify, review, commit.

Parallel policy:

- Tasks 1 and 2 are shared-core and must be sequential.
- After Task 2 freezes the projection shape, Task 3 and Task 4 can be split between two workers if both read the committed contract and do not edit the same files.
- Task 5 should run after Task 4 because App rendering depends on the UI model.
- Task 6 is final integration and must be single-owner.

Human approval gates:

- No approval gate inside implementation unless a test proves the approved schema cannot support an existing runtime state.
- If the executor wants to change `waygent.operator_decision.v1` field names after Task 2, pause and revise this plan before continuing.

## Task 1: Add Operator Decision Contract

**Files:**

- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/contracts/tests/contracts.test.ts`

- [ ] **Step 1: Write the failing contract test**

Append this test to `packages/contracts/tests/contracts.test.ts` inside the existing `describe("Waygent contracts", () => { ... })` block:

```ts
  test("validates operator decision projection contract", () => {
    const decision = {
      schema: "waygent.operator_decision.v1",
      run_id: "run_demo",
      generated_at: "2026-05-22T00:00:00.000Z",
      status_summary: {
        display_status: "blocked",
        runtime_status: "blocked",
        lifecycle_outcome: "blocked",
        current_phase: "recover",
        active_tasks: 0,
        completed_tasks: 0,
        blocked_tasks: 1,
        apply_status: "blocked",
        summary: "run_demo is blocked by verification_failed."
      },
      primary_blocker: {
        code: "verification_failed",
        title: "Verification failed",
        summary: "task_demo failed verification.",
        severity: "blocking",
        task_id: "task_demo",
        evidence_refs: ["state:/tmp/run/state.json", "verification:task_demo"],
        missing_refs: [],
        recommended_action_ids: ["rerun_verification", "open_ai_repair_handoff"]
      },
      secondary_blockers: [],
      allowed_actions: [
        {
          id: "inspect_run",
          label: "Inspect run",
          reason: "Inspection is always safe.",
          evidence_refs: ["state:/tmp/run/state.json"],
          requires_approval: false,
          requires_runtime_revalidation: false,
          command: "waygent inspect --run run_demo"
        },
        {
          id: "open_ai_repair_handoff",
          label: "Open AI repair handoff",
          reason: "AI can draft a repair plan from bounded evidence.",
          evidence_refs: ["state:/tmp/run/state.json"],
          requires_approval: false,
          requires_runtime_revalidation: false,
          command: null
        }
      ],
      blocked_actions: [
        {
          id: "apply_run",
          label: "Apply run",
          reason: "Apply readiness is blocked by verification_failed.",
          evidence_refs: ["state:/tmp/run/state.json"],
          unblocks_when: "Verification and apply readiness pass."
        }
      ],
      evidence_packet: {
        state_refs: ["state:/tmp/run/state.json"],
        event_refs: ["events:/tmp/run/events.jsonl"],
        artifact_refs: [],
        verification_refs: ["verification:task_demo"],
        checkpoint_refs: [],
        projection_refs: ["waygent.execution_explanation.v1"],
        missing_refs: [],
        redaction_notes: []
      },
      ai_handoff: {
        purpose: "draft_repair_plan",
        prompt_summary: "Draft a repair plan for verification_failed using bounded evidence.",
        run_id: "run_demo",
        current_status: "blocked",
        primary_blocker: "verification_failed",
        secondary_blockers: [],
        allowed_action_ids: ["inspect_run", "open_ai_repair_handoff"],
        blocked_action_ids: ["apply_run"],
        constraints: [
          "Do not apply patches.",
          "Do not mutate source.",
          "Do not override Waygent runtime policy."
        ],
        evidence_refs: ["state:/tmp/run/state.json", "verification:task_demo"],
        missing_evidence: [],
        raw_fallback_refs: ["events:/tmp/run/events.jsonl"],
        safety_notes: ["Waygent runtime remains apply authority."]
      },
      confidence: "deterministic",
      unknown_reasons: [],
      source_projection_refs: {
        run_state_v2: "state:/tmp/run/state.json",
        apply_readiness: "waygent.apply_readiness",
        execution_explanation: "waygent.execution_explanation.v1",
        operational_maturity: "waygent.operational_maturity.v1"
      }
    };

    expect(validateContract("waygent.operator_decision.v1", decision)).toEqual(decision);
    expect(() =>
      validateContract("waygent.operator_decision.v1", {
        ...decision,
        [["legacy", "source"].join("_")]: "components/agentlens"
      })
    ).toThrow(ContractValidationError);
  });
```

- [ ] **Step 2: Run the contract test and verify it fails for the missing schema**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
```

Expected: fail with `Unknown contract schema waygent.operator_decision.v1`.

- [ ] **Step 3: Add shared TypeScript types**

Insert this block in `packages/contracts/src/types.ts` after `OperationalMaturityProjection`:

```ts
export type OperatorDecisionConfidence = "deterministic" | "partial" | "unknown";
export type OperatorRunStatus =
  | "running"
  | "recovering"
  | "needs_input"
  | "needs_approval"
  | "blocked"
  | "ready_to_apply"
  | "done"
  | "failed";

export type OperatorBlockerSeverity = "info" | "warning" | "blocking" | "critical";
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
  | "apply_run";

export interface OperatorStatusSummary {
  display_status: OperatorRunStatus;
  runtime_status: WaygentRunStatusV2 | "missing" | "invalid" | "unsupported";
  lifecycle_outcome: WaygentLifecycleOutcome;
  current_phase: WaygentCurrentPhase | null;
  active_tasks: number;
  completed_tasks: number;
  blocked_tasks: number;
  apply_status: ApplyReadinessProjection["status"] | "unknown";
  summary: string;
}

export interface OperatorBlocker {
  code: string;
  title: string;
  summary: string;
  severity: OperatorBlockerSeverity;
  task_id?: string;
  evidence_refs: string[];
  missing_refs: string[];
  recommended_action_ids: OperatorActionId[];
}

export interface OperatorAllowedAction {
  id: OperatorActionId;
  label: string;
  reason: string;
  evidence_refs: string[];
  requires_approval: boolean;
  requires_runtime_revalidation: boolean;
  command: string | null;
}

export interface OperatorBlockedAction {
  id: OperatorActionId;
  label: string;
  reason: string;
  evidence_refs: string[];
  unblocks_when: string;
}

export interface OperatorEvidencePacket {
  state_refs: string[];
  event_refs: string[];
  artifact_refs: string[];
  verification_refs: string[];
  checkpoint_refs: string[];
  projection_refs: string[];
  missing_refs: string[];
  redaction_notes: string[];
}

export interface OperatorAiHandoff {
  purpose: "draft_repair_plan" | "summarize_blocker" | "compare_recovery_options";
  prompt_summary: string;
  run_id: string;
  current_status: OperatorRunStatus;
  primary_blocker: string | null;
  secondary_blockers: string[];
  allowed_action_ids: OperatorActionId[];
  blocked_action_ids: OperatorActionId[];
  constraints: string[];
  evidence_refs: string[];
  missing_evidence: string[];
  raw_fallback_refs: string[];
  safety_notes: string[];
}

export interface OperatorSourceProjectionRefs {
  run_state_v2: string | null;
  apply_readiness: string | null;
  execution_explanation: string | null;
  operational_maturity: string | null;
}

export type OperatorTimelineRowType =
  | "safe_wave"
  | "task_packet"
  | "provider_attempt"
  | "worker_result"
  | "verification_result"
  | "checkpoint"
  | "review_finding"
  | "recovery_decision"
  | "apply_readiness"
  | "artifact_health"
  | "provider_readiness"
  | "raw_event";

export interface OperatorTimelineRow {
  id: string;
  sequence: number;
  timestamp: string | null;
  actor: string;
  row_type: OperatorTimelineRowType;
  title: string;
  outcome: EventOutcome | "unknown";
  severity: EventSeverity;
  task_id: string | null;
  evidence_refs: string[];
  metadata: Record<string, unknown>;
}

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
  source_projection_refs: OperatorSourceProjectionRefs;
}
```

- [ ] **Step 4: Add the JSON schema**

In `packages/contracts/src/schemas.ts`, add value arrays near the existing enum arrays:

```ts
const operatorRunStatusValues = [
  "running",
  "recovering",
  "needs_input",
  "needs_approval",
  "blocked",
  "ready_to_apply",
  "done",
  "failed"
] as const;
const operatorActionIdValues = [
  "inspect_run",
  "explain_run",
  "open_raw_evidence",
  "open_ai_repair_handoff",
  "request_user_input",
  "approve_recovery",
  "resume_run",
  "regenerate_checkpoint",
  "rebase_checkpoint",
  "rerun_verification",
  "review_patch",
  "apply_run"
] as const;
```

Add `operatorDecisionProjectionSchema` before `export const schemas = { ... }`:

```ts
const operatorBlockerSchema = {
  type: "object",
  additionalProperties: false,
  required: ["code", "title", "summary", "severity", "evidence_refs", "missing_refs", "recommended_action_ids"],
  properties: {
    code: { type: "string", minLength: 1 },
    title: { type: "string", minLength: 1 },
    summary: { type: "string", minLength: 1 },
    severity: { enum: ["info", "warning", "blocking", "critical"] },
    task_id: { type: "string", pattern: idPattern, nullable: true },
    evidence_refs: { type: "array", items: { type: "string", minLength: 1 } },
    missing_refs: { type: "array", items: { type: "string", minLength: 1 } },
    recommended_action_ids: { type: "array", items: { enum: operatorActionIdValues } }
  }
} as const;

const operatorAllowedActionSchema = {
  type: "object",
  additionalProperties: false,
  required: ["id", "label", "reason", "evidence_refs", "requires_approval", "requires_runtime_revalidation", "command"],
  properties: {
    id: { enum: operatorActionIdValues },
    label: { type: "string", minLength: 1 },
    reason: { type: "string", minLength: 1 },
    evidence_refs: { type: "array", items: { type: "string", minLength: 1 } },
    requires_approval: { type: "boolean" },
    requires_runtime_revalidation: { type: "boolean" },
    command: { type: "string", nullable: true }
  }
} as const;

const operatorBlockedActionSchema = {
  type: "object",
  additionalProperties: false,
  required: ["id", "label", "reason", "evidence_refs", "unblocks_when"],
  properties: {
    id: { enum: operatorActionIdValues },
    label: { type: "string", minLength: 1 },
    reason: { type: "string", minLength: 1 },
    evidence_refs: { type: "array", items: { type: "string", minLength: 1 } },
    unblocks_when: { type: "string", minLength: 1 }
  }
} as const;

const operatorEvidencePacketSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "state_refs",
    "event_refs",
    "artifact_refs",
    "verification_refs",
    "checkpoint_refs",
    "projection_refs",
    "missing_refs",
    "redaction_notes"
  ],
  properties: {
    state_refs: { type: "array", items: { type: "string", minLength: 1 } },
    event_refs: { type: "array", items: { type: "string", minLength: 1 } },
    artifact_refs: { type: "array", items: { type: "string", minLength: 1 } },
    verification_refs: { type: "array", items: { type: "string", minLength: 1 } },
    checkpoint_refs: { type: "array", items: { type: "string", minLength: 1 } },
    projection_refs: { type: "array", items: { type: "string", minLength: 1 } },
    missing_refs: { type: "array", items: { type: "string", minLength: 1 } },
    redaction_notes: { type: "array", items: { type: "string", minLength: 1 } }
  }
} as const;

export const operatorDecisionProjectionSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schema",
    "run_id",
    "generated_at",
    "status_summary",
    "primary_blocker",
    "secondary_blockers",
    "allowed_actions",
    "blocked_actions",
    "evidence_packet",
    "ai_handoff",
    "confidence",
    "unknown_reasons",
    "source_projection_refs"
  ],
  properties: {
    schema: { const: "waygent.operator_decision.v1" },
    run_id: { type: "string", pattern: idPattern },
    generated_at: { type: "string", pattern: isoTimestamp },
    status_summary: {
      type: "object",
      additionalProperties: false,
      required: [
        "display_status",
        "runtime_status",
        "lifecycle_outcome",
        "current_phase",
        "active_tasks",
        "completed_tasks",
        "blocked_tasks",
        "apply_status",
        "summary"
      ],
      properties: {
        display_status: { enum: operatorRunStatusValues },
        runtime_status: { enum: ["initializing", "running", "blocked", "failed", "completed", "applying", "applied", "missing", "invalid", "unsupported"] },
        lifecycle_outcome: { enum: ["finished", "blocked", "failed", "aborted", null] },
        current_phase: { enum: ["preflight", "dispatch", "review", "verify", "recover", "apply", "complete", null] },
        active_tasks: { type: "integer", minimum: 0 },
        completed_tasks: { type: "integer", minimum: 0 },
        blocked_tasks: { type: "integer", minimum: 0 },
        apply_status: { enum: ["ready", "not_ready", "blocked", "applied", "unknown"] },
        summary: { type: "string", minLength: 1 }
      }
    },
    primary_blocker: { ...operatorBlockerSchema, nullable: true },
    secondary_blockers: { type: "array", items: operatorBlockerSchema },
    allowed_actions: { type: "array", items: operatorAllowedActionSchema },
    blocked_actions: { type: "array", items: operatorBlockedActionSchema },
    evidence_packet: operatorEvidencePacketSchema,
    ai_handoff: {
      type: "object",
      additionalProperties: false,
      required: [
        "purpose",
        "prompt_summary",
        "run_id",
        "current_status",
        "primary_blocker",
        "secondary_blockers",
        "allowed_action_ids",
        "blocked_action_ids",
        "constraints",
        "evidence_refs",
        "missing_evidence",
        "raw_fallback_refs",
        "safety_notes"
      ],
      properties: {
        purpose: { enum: ["draft_repair_plan", "summarize_blocker", "compare_recovery_options"] },
        prompt_summary: { type: "string", minLength: 1 },
        run_id: { type: "string", pattern: idPattern },
        current_status: { enum: operatorRunStatusValues },
        primary_blocker: { type: "string", nullable: true },
        secondary_blockers: { type: "array", items: { type: "string", minLength: 1 } },
        allowed_action_ids: { type: "array", items: { enum: operatorActionIdValues } },
        blocked_action_ids: { type: "array", items: { enum: operatorActionIdValues } },
        constraints: { type: "array", items: { type: "string", minLength: 1 } },
        evidence_refs: { type: "array", items: { type: "string", minLength: 1 } },
        missing_evidence: { type: "array", items: { type: "string", minLength: 1 } },
        raw_fallback_refs: { type: "array", items: { type: "string", minLength: 1 } },
        safety_notes: { type: "array", items: { type: "string", minLength: 1 } }
      }
    },
    confidence: { enum: ["deterministic", "partial", "unknown"] },
    unknown_reasons: { type: "array", items: { type: "string", minLength: 1 } },
    source_projection_refs: {
      type: "object",
      additionalProperties: false,
      required: ["run_state_v2", "apply_readiness", "execution_explanation", "operational_maturity"],
      properties: {
        run_state_v2: { type: "string", nullable: true },
        apply_readiness: { type: "string", nullable: true },
        execution_explanation: { type: "string", nullable: true },
        operational_maturity: { type: "string", nullable: true }
      }
    }
  }
} as const;
```

Add the schema to the `schemas` object:

```ts
  "waygent.operator_decision.v1": operatorDecisionProjectionSchema
```

- [ ] **Step 5: Run contract test and typecheck**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
bun run typecheck
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit Task 1**

```bash
git add packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/contracts/tests/contracts.test.ts
git commit -m "feat: add operator decision contract"
```

## Task 2: Add Pure Operator Decision Projector

**Files:**

- Create: `packages/lens-projectors/src/operatorDecision.ts`
- Create: `packages/lens-projectors/tests/operatorDecision.test.ts`
- Modify: `packages/lens-projectors/src/index.ts`

- [ ] **Step 1: Write projector tests**

Create `packages/lens-projectors/tests/operatorDecision.test.ts` with this file:

```ts
import { describe, expect, test } from "bun:test";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { projectOperatorDecisionFromState } from "../src";
import { demoEvent } from "./support";

describe("operator decision projector", () => {
  test("allows apply only when apply readiness is ready", () => {
    const state = makeState({
      completion_audit: {
        status: "passed",
        combined_apply_evidence: {
          status: "passed",
          checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
          patch_ref: "artifacts/checkpoints/apply/run_ready.patch"
        }
      }
    });

    const projection = projectOperatorDecisionFromState({
      state,
      events: [demoEvent({ event_type: "runway.verification_result", outcome: "success" })]
    });

    expect(projection).toMatchObject({
      schema: "waygent.operator_decision.v1",
      run_id: "run_demo",
      confidence: "deterministic",
      primary_blocker: null,
      status_summary: {
        display_status: "ready_to_apply",
        apply_status: "ready"
      }
    });
    expect(projection.allowed_actions.map((action) => action.id)).toContain("apply_run");
    expect(projection.blocked_actions.map((action) => action.id)).not.toContain("apply_run");
  });

  test("blocks apply and exposes repair handoff for verification failure", () => {
    const projection = projectOperatorDecisionFromState({
      state: makeState({
        status: "blocked",
        lifecycle_outcome: "blocked",
        current_phase: "recover",
        tasks: {
          task_a: task("task_a", {
            status: "blocked",
            latest_failure_class: "verification_failed",
            checkpoint_refs: []
          })
        },
        verification: [{ verification_id: "verify_task_a_1", task_id: "task_a", command: "bun test", status: "failed" }],
        apply: { status: "blocked", reason: "verification_failed" }
      }),
      events: [demoEvent({ event_type: "runway.verification_result", outcome: "failed", summary: "Verification failed." })]
    });

    expect(projection.primary_blocker).toMatchObject({
      code: "verification_failed",
      task_id: "task_a",
      severity: "blocking"
    });
    expect(projection.allowed_actions.map((action) => action.id)).toEqual([
      "inspect_run",
      "explain_run",
      "open_raw_evidence",
      "open_ai_repair_handoff",
      "rerun_verification"
    ]);
    expect(projection.blocked_actions).toContainEqual(expect.objectContaining({
      id: "apply_run",
      reason: expect.stringContaining("verification_failed")
    }));
    expect(projection.ai_handoff.constraints).toContain("Do not apply patches.");
    expect(projection.ai_handoff.evidence_refs).toContain("verification:task_a");
  });

  test("classifies checkpoint dry-run conflict as needs_rebase", () => {
    const projection = projectOperatorDecisionFromState({
      state: makeState({
        status: "blocked",
        lifecycle_outcome: "blocked",
        current_phase: "recover",
        tasks: {
          task_a: task("task_a", {
            status: "blocked",
            latest_failure_class: "needs_rebase",
            checkpoint_refs: []
          })
        },
        drift: {
          last_checked_at: "2026-05-22T00:01:00.000Z",
          records: [{ failure_class: "needs_rebase", files: ["README.md"] }],
          unrepaired_blockers: [{ failure_class: "needs_rebase", files: ["README.md"] }]
        },
        apply: { status: "blocked", reason: "needs_rebase" }
      }),
      events: []
    });

    expect(projection.primary_blocker).toMatchObject({
      code: "needs_rebase",
      recommended_action_ids: ["regenerate_checkpoint", "rebase_checkpoint", "open_ai_repair_handoff"]
    });
    expect(projection.allowed_actions.map((action) => action.id)).toContain("regenerate_checkpoint");
    expect(projection.allowed_actions.map((action) => action.id)).toContain("rebase_checkpoint");
  });

  test("degrades missing state to unknown confidence with raw evidence only", () => {
    const projection = projectOperatorDecisionFromState({
      state: null,
      state_error: { status: "missing", reason: "missing_run_state_v2" },
      events: [demoEvent({ event_type: "runway.worker_result", outcome: "success" })],
      run_id: "run_missing"
    });

    expect(projection).toMatchObject({
      run_id: "run_missing",
      confidence: "unknown",
      primary_blocker: {
        code: "state_missing",
        severity: "critical"
      }
    });
    expect(projection.allowed_actions.map((action) => action.id)).toEqual([
      "inspect_run",
      "open_raw_evidence"
    ]);
    expect(projection.blocked_actions.map((action) => action.id)).toContain("apply_run");
  });

  test("marks missing evidence as partial confidence", () => {
    const projection = projectOperatorDecisionFromState({
      state: makeState({
        artifact_index: [],
        tasks: {
          task_a: task("task_a", {
            status: "verified",
            checkpoint_refs: []
          })
        },
        apply: { status: "not_ready" },
        completion_audit: { status: "passed" }
      }),
      events: []
    });

    expect(projection.confidence).toBe("partial");
    expect(projection.evidence_packet.missing_refs).toContain("checkpoint_refs");
    expect(projection.primary_blocker).toMatchObject({
      code: "checkpoint_missing"
    });
  });
});

function task(id: string, overrides: Partial<WaygentRunStateV2["tasks"][string]> = {}): WaygentRunStateV2["tasks"][string] {
  return {
    id,
    status: "verified",
    risk: "low",
    dependencies: [],
    file_claims: [{ path: `${id}.txt`, mode: "owned" }],
    attempts: [],
    task_packet_path: null,
    task_packet_sha256: null,
    unit_manifest: null,
    checkpoint_refs: [`artifacts/checkpoints/${id}/candidate_${id}.json`],
    latest_failure_class: null,
    decision_packet_ref: null,
    timing: {},
    ...overrides
  };
}

function makeState(overrides: Partial<WaygentRunStateV2> = {}): WaygentRunStateV2 {
  return {
    schema: "waygent.run_state.v2",
    run_id: "run_demo",
    workspace: "/tmp/source",
    source_branch: "main",
    worktree_root: "/tmp/worktrees",
    run_root: "/tmp/run_demo",
    artifact_root: "/tmp/run_demo/artifacts",
    state_path: "/tmp/run_demo/state.json",
    event_journal_path: "/tmp/run_demo/events.jsonl",
    plan_path: null,
    spec_path: null,
    provider_profile: { provider: "fake" },
    status: "completed",
    lifecycle_outcome: "finished",
    current_phase: "complete",
    tasks: { task_a: task("task_a") },
    safe_waves: [],
    provider_attempts: [],
    reviews: [],
    verification: [],
    recovery: [],
    apply: { status: "not_applied" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: null,
    timestamps: {
      started_at: "2026-05-22T00:00:00.000Z",
      updated_at: "2026-05-22T00:00:03.000Z",
      completed_at: "2026-05-22T00:00:03.000Z"
    },
    ...overrides
  };
}
```

- [ ] **Step 2: Run projector test and verify it fails because the export does not exist**

Run:

```bash
bun test packages/lens-projectors/tests/operatorDecision.test.ts
```

Expected: fail because `projectOperatorDecisionFromState` is not exported.

- [ ] **Step 3: Implement the pure projector**

Create `packages/lens-projectors/src/operatorDecision.ts` with this structure. Keep helper functions local until another projector needs them.

```ts
import type {
  AgentLensEvent,
  ApplyReadinessProjection,
  ExecutionExplanationProjection,
  FailureClass,
  OperationalMaturityProjection,
  OperatorActionId,
  OperatorAllowedAction,
  OperatorAiHandoff,
  OperatorBlockedAction,
  OperatorBlocker,
  OperatorDecisionConfidence,
  OperatorDecisionProjection,
  OperatorEvidencePacket,
  OperatorRunStatus,
  OperatorStatusSummary,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectApplyReadinessFromState } from "./apply";
import { projectExecutionExplanationFromState } from "./executionExplanation";
import { projectOperationalMaturityFromState } from "./operationalMaturity";

export interface OperatorDecisionInput {
  state: WaygentRunStateV2 | null;
  events: AgentLensEvent[];
  run_id?: string;
  state_error?: { status: string; reason: string };
  apply_readiness?: ApplyReadinessProjection | null;
  execution_explanation?: ExecutionExplanationProjection | null;
  operational_maturity?: OperationalMaturityProjection | null;
}

const blockerPriority = new Map<string, number>([
  ["state_invalid", 1],
  ["state_missing", 1],
  ["unsafe_apply", 2],
  ["checkpoint_digest_mismatch", 2],
  ["runtime_active", 3],
  ["needs_user_input", 4],
  ["needs_approval", 4],
  ["verification_failed", 5],
  ["checkpoint_dry_run_failed", 6],
  ["needs_rebase", 6],
  ["checkpoint_missing", 7],
  ["artifact_missing", 7],
  ["evidence_incomplete", 8],
  ["provider_not_ready", 9],
  ["runtime_cost_warning", 10],
  ["unknown_failure", 99]
]);

export function projectOperatorDecisionFromState(input: OperatorDecisionInput): OperatorDecisionProjection {
  const runId = input.state?.run_id ?? input.run_id ?? input.events[0]?.orchestrator_run_id ?? input.events[0]?.agentlens_run_id ?? "run_unknown";
  const generatedAt = input.state?.timestamps.updated_at ?? input.events.at(-1)?.occurred_at ?? new Date(0).toISOString();

  if (!input.state) {
    const missingRef = input.state_error?.reason ?? "missing_run_state_v2";
    const blocker = blocker("state_missing", "Run state is missing", "Waygent v2 run state is unavailable.", "critical", null, [], [missingRef], ["inspect_run", "open_raw_evidence"]);
    const evidence = evidencePacket({
      event_refs: eventRefs(input.events),
      missing_refs: [missingRef],
      projection_refs: []
    });
    const allowed = [
      allowed("inspect_run", runId, "Inspection can still show event-derived evidence.", evidence.event_refs, false, false),
      allowed("open_raw_evidence", runId, "Raw event evidence is available for manual inspection.", evidence.event_refs, false, false)
    ];
    const blocked = blockUnsafeActions("Run state is missing.", evidence.event_refs);
    return decision(runId, generatedAt, statusSummaryMissing("missing", "Run state is missing."), blocker, [], allowed, blocked, evidence, "unknown", [missingRef]);
  }

  const state = input.state;
  const applyReadiness = input.apply_readiness ?? projectApplyReadinessFromState(state);
  const executionExplanation = input.execution_explanation ?? projectExecutionExplanationFromState(state);
  const operationalMaturity = input.operational_maturity ?? projectOperationalMaturityFromState({ state, events: input.events });
  const evidence = evidencePacket({
    state_refs: [`state:${state.state_path}`],
    event_refs: [`events:${state.event_journal_path}`],
    artifact_refs: artifactRefs(state),
    verification_refs: verificationRefs(state),
    checkpoint_refs: applyReadiness.checkpoint_refs,
    projection_refs: [
      executionExplanation.schema,
      operationalMaturity.schema,
      operationalMaturity.dogfood_evidence.schema,
      operationalMaturity.runtime_cost.schema,
      operationalMaturity.provider_readiness.schema
    ],
    missing_refs: missingEvidence(state, applyReadiness)
  });
  const blockers = collectBlockers(state, applyReadiness, operationalMaturity, evidence);
  const sortedBlockers = blockers.sort((left, right) => priority(left.code) - priority(right.code));
  const primary = sortedBlockers[0] ?? null;
  const secondary = primary ? sortedBlockers.slice(1) : [];
  const displayStatus = displayStatusFor(state, applyReadiness, primary);
  const confidence = confidenceFor(primary, evidence);
  const allowedActions = allowedActionsFor(runId, primary, applyReadiness, evidence);
  const blockedActions = blockedActionsFor(primary, applyReadiness, evidence);
  const summary = primary
    ? `${state.run_id} is ${displayStatus} by ${primary.code}.`
    : `${state.run_id} is ${displayStatus}.`;

  return {
    schema: "waygent.operator_decision.v1",
    run_id: state.run_id,
    generated_at: generatedAt,
    status_summary: {
      display_status: displayStatus,
      runtime_status: state.status,
      lifecycle_outcome: state.lifecycle_outcome,
      current_phase: state.current_phase,
      active_tasks: Object.values(state.tasks).filter((task) => task.status === "running").length,
      completed_tasks: Object.values(state.tasks).filter((task) => task.status === "verified" || task.status === "applied").length,
      blocked_tasks: Object.values(state.tasks).filter((task) => task.status === "blocked" || task.status === "failed").length,
      apply_status: applyReadiness.status,
      summary
    },
    primary_blocker: primary,
    secondary_blockers: secondary,
    allowed_actions: allowedActions,
    blocked_actions: blockedActions,
    evidence_packet: evidence,
    ai_handoff: aiHandoff(state.run_id, displayStatus, primary, secondary, allowedActions, blockedActions, evidence),
    confidence,
    unknown_reasons: confidence === "unknown" ? evidence.missing_refs : [],
    source_projection_refs: {
      run_state_v2: `state:${state.state_path}`,
      apply_readiness: "waygent.apply_readiness",
      execution_explanation: executionExplanation.schema,
      operational_maturity: operationalMaturity.schema
    }
  };
}

function collectBlockers(
  state: WaygentRunStateV2,
  applyReadiness: ApplyReadinessProjection,
  maturity: OperationalMaturityProjection,
  evidence: OperatorEvidencePacket
): OperatorBlocker[] {
  const result: OperatorBlocker[] = [];
  if (state.status === "running" || state.status === "applying" || state.status === "initializing") {
    result.push(blocker("runtime_active", "Runtime is active", "Mutation is blocked while Waygent is active.", "blocking", null, evidence.state_refs, [], ["inspect_run"]));
  }
  for (const task of Object.values(state.tasks)) {
    if (task.latest_failure_class) {
      result.push(blockerFromFailure(task.id, task.latest_failure_class, evidence));
    }
  }
  if (applyReadiness.status === "blocked") {
    result.push(blocker("apply_blocked", "Apply is blocked", `Apply readiness is blocked by ${applyReadiness.reason ?? "unknown reason"}.`, "blocking", null, evidence.state_refs, [], ["inspect_run", "open_raw_evidence"]));
  }
  if (applyReadiness.status === "not_ready" && evidence.checkpoint_refs.length === 0) {
    result.push(blocker("checkpoint_missing", "Checkpoint evidence is missing", "No apply-ready checkpoint refs are available.", "blocking", null, evidence.state_refs, ["checkpoint_refs"], ["inspect_run", "open_raw_evidence"]));
  }
  if (maturity.provider_readiness.status !== "ready" && maturity.provider_readiness.status !== "unknown") {
    result.push(blocker("provider_not_ready", "Provider is not ready", maturity.provider_readiness.recommended_next_action, "warning", null, maturity.provider_readiness.attempt_refs, [], ["inspect_run"]));
  }
  if (evidence.missing_refs.length > 0 && result.length === 0) {
    result.push(blocker("evidence_incomplete", "Evidence is incomplete", "Required evidence is missing for deterministic action guidance.", "warning", null, evidence.state_refs, evidence.missing_refs, ["inspect_run", "open_raw_evidence"]));
  }
  return dedupeBlockers(result);
}

function blockerFromFailure(taskId: string, failureClass: FailureClass | string, evidence: OperatorEvidencePacket): OperatorBlocker {
  if (failureClass === "verification_failed") {
    return blocker("verification_failed", "Verification failed", `${taskId} failed verification.`, "blocking", taskId, ["verification:" + taskId, ...evidence.state_refs], [], ["rerun_verification", "open_ai_repair_handoff"]);
  }
  if (failureClass === "needs_rebase") {
    return blocker("needs_rebase", "Checkpoint needs rebase", `${taskId} checkpoint no longer applies cleanly to current source.`, "blocking", taskId, evidence.state_refs, [], ["regenerate_checkpoint", "rebase_checkpoint", "open_ai_repair_handoff"]);
  }
  if (failureClass === "missing_checkpoint") {
    return blocker("checkpoint_missing", "Checkpoint is missing", `${taskId} has no verified checkpoint refs.`, "blocking", taskId, evidence.state_refs, ["checkpoint_refs"], ["inspect_run", "open_raw_evidence"]);
  }
  return blocker(String(failureClass), "Runtime failure", `${taskId} is blocked by ${failureClass}.`, "blocking", taskId, evidence.state_refs, [], ["inspect_run", "open_ai_repair_handoff"]);
}

function allowedActionsFor(
  runId: string,
  primary: OperatorBlocker | null,
  applyReadiness: ApplyReadinessProjection,
  evidence: OperatorEvidencePacket
): OperatorAllowedAction[] {
  const result = [
    allowed("inspect_run", runId, "Inspection is always safe.", evidence.state_refs, false, false),
    allowed("explain_run", runId, "Explanation is read-only.", evidence.state_refs, false, false),
    allowed("open_raw_evidence", runId, "Raw evidence can be inspected without mutation.", rawRefs(evidence), false, false)
  ];
  if (primary) {
    result.push(allowed("open_ai_repair_handoff", runId, "AI can draft a repair plan from bounded evidence.", evidence.state_refs, false, false));
  }
  if (primary?.code === "verification_failed") {
    result.push(allowed("rerun_verification", runId, "Verification can be rerun after the operator reviews the failure.", primary.evidence_refs, true, true));
  }
  if (primary?.code === "needs_rebase") {
    result.push(allowed("regenerate_checkpoint", runId, "Checkpoint can be regenerated against current source.", primary.evidence_refs, true, true));
    result.push(allowed("rebase_checkpoint", runId, "Checkpoint can be rebased against current source.", primary.evidence_refs, true, true));
  }
  if (!primary && applyReadiness.status === "ready") {
    result.push(allowed("apply_run", runId, "Apply readiness is ready; runtime must revalidate before applying.", evidence.checkpoint_refs, true, true));
  }
  return dedupeActions(result);
}

function blockedActionsFor(primary: OperatorBlocker | null, applyReadiness: ApplyReadinessProjection, evidence: OperatorEvidencePacket): OperatorBlockedAction[] {
  if (applyReadiness.status === "ready" && !primary) return [];
  const reason = primary?.code ?? applyReadiness.reason ?? "missing_apply_ready_evidence";
  return blockUnsafeActions(`Apply readiness is blocked by ${reason}.`, primary?.evidence_refs.length ? primary.evidence_refs : evidence.state_refs);
}

function displayStatusFor(state: WaygentRunStateV2, applyReadiness: ApplyReadinessProjection, primary: OperatorBlocker | null): OperatorRunStatus {
  if (state.status === "failed") return "failed";
  if (state.status === "running" || state.status === "initializing") return "running";
  if (state.current_phase === "recover") return "recovering";
  if (primary?.code === "needs_approval") return "needs_approval";
  if (primary?.code === "needs_user_input") return "needs_input";
  if (primary) return "blocked";
  if (applyReadiness.status === "ready") return "ready_to_apply";
  if (state.status === "completed" || state.status === "applied") return "done";
  return "blocked";
}

function confidenceFor(primary: OperatorBlocker | null, evidence: OperatorEvidencePacket): OperatorDecisionConfidence {
  if (primary?.code === "state_missing" || primary?.code === "state_invalid") return "unknown";
  if (evidence.missing_refs.length > 0) return "partial";
  return "deterministic";
}

function aiHandoff(
  runId: string,
  currentStatus: OperatorRunStatus,
  primary: OperatorBlocker | null,
  secondary: OperatorBlocker[],
  allowedActions: OperatorAllowedAction[],
  blockedActions: OperatorBlockedAction[],
  evidence: OperatorEvidencePacket
): OperatorAiHandoff {
  return {
    purpose: primary ? "draft_repair_plan" : "summarize_blocker",
    prompt_summary: primary
      ? `Draft a repair plan for ${primary.code} using bounded evidence.`
      : "Summarize the current run state using bounded evidence.",
    run_id: runId,
    current_status: currentStatus,
    primary_blocker: primary?.code ?? null,
    secondary_blockers: secondary.map((item) => item.code),
    allowed_action_ids: allowedActions.map((action) => action.id),
    blocked_action_ids: blockedActions.map((action) => action.id),
    constraints: [
      "Do not apply patches.",
      "Do not mutate source.",
      "Do not resume execution.",
      "Do not override Waygent runtime policy."
    ],
    evidence_refs: [...new Set([...evidence.state_refs, ...evidence.verification_refs, ...evidence.checkpoint_refs])],
    missing_evidence: evidence.missing_refs,
    raw_fallback_refs: rawRefs(evidence),
    safety_notes: ["Waygent runtime remains apply authority."]
  };
}

function blocker(
  code: string,
  title: string,
  summary: string,
  severity: OperatorBlocker["severity"],
  taskId: string | null,
  evidenceRefs: string[],
  missingRefs: string[],
  recommendedActionIds: OperatorActionId[]
): OperatorBlocker {
  return {
    code,
    title,
    summary,
    severity,
    ...(taskId ? { task_id: taskId } : {}),
    evidence_refs: [...new Set(evidenceRefs)],
    missing_refs: [...new Set(missingRefs)],
    recommended_action_ids: recommendedActionIds
  };
}

function allowed(
  id: OperatorActionId,
  runId: string,
  reason: string,
  evidenceRefs: string[],
  requiresApproval: boolean,
  requiresRuntimeRevalidation: boolean
): OperatorAllowedAction {
  return {
    id,
    label: labelForAction(id),
    reason,
    evidence_refs: [...new Set(evidenceRefs)],
    requires_approval: requiresApproval,
    requires_runtime_revalidation: requiresRuntimeRevalidation,
    command: commandForAction(id, runId)
  };
}

function blockUnsafeActions(reason: string, evidenceRefs: string[]): OperatorBlockedAction[] {
  return [{
    id: "apply_run",
    label: "Apply run",
    reason,
    evidence_refs: [...new Set(evidenceRefs)],
    unblocks_when: "Apply readiness is ready and Waygent runtime revalidation passes."
  }];
}

function evidencePacket(overrides: Partial<OperatorEvidencePacket>): OperatorEvidencePacket {
  return {
    state_refs: overrides.state_refs ?? [],
    event_refs: overrides.event_refs ?? [],
    artifact_refs: overrides.artifact_refs ?? [],
    verification_refs: overrides.verification_refs ?? [],
    checkpoint_refs: overrides.checkpoint_refs ?? [],
    projection_refs: overrides.projection_refs ?? [],
    missing_refs: overrides.missing_refs ?? [],
    redaction_notes: overrides.redaction_notes ?? []
  };
}

function decision(
  runId: string,
  generatedAt: string,
  statusSummary: OperatorStatusSummary,
  primary: OperatorBlocker,
  secondary: OperatorBlocker[],
  allowedActions: OperatorAllowedAction[],
  blockedActions: OperatorBlockedAction[],
  evidence: OperatorEvidencePacket,
  confidence: OperatorDecisionConfidence,
  unknownReasons: string[]
): OperatorDecisionProjection {
  return {
    schema: "waygent.operator_decision.v1",
    run_id: runId,
    generated_at: generatedAt,
    status_summary: statusSummary,
    primary_blocker: primary,
    secondary_blockers: secondary,
    allowed_actions: allowedActions,
    blocked_actions: blockedActions,
    evidence_packet: evidence,
    ai_handoff: aiHandoff(runId, statusSummary.display_status, primary, secondary, allowedActions, blockedActions, evidence),
    confidence,
    unknown_reasons: unknownReasons,
    source_projection_refs: {
      run_state_v2: null,
      apply_readiness: null,
      execution_explanation: null,
      operational_maturity: null
    }
  };
}

function statusSummaryMissing(runtimeStatus: "missing" | "invalid" | "unsupported", summary: string): OperatorStatusSummary {
  return {
    display_status: "blocked",
    runtime_status: runtimeStatus,
    lifecycle_outcome: null,
    current_phase: null,
    active_tasks: 0,
    completed_tasks: 0,
    blocked_tasks: 0,
    apply_status: "unknown",
    summary
  };
}

function missingEvidence(state: WaygentRunStateV2, applyReadiness: ApplyReadinessProjection): string[] {
  const missing = new Set<string>();
  if (Object.values(state.tasks).some((task) => task.status === "verified" && task.checkpoint_refs.length === 0)) missing.add("checkpoint_refs");
  if (applyReadiness.status === "not_ready" && applyReadiness.checkpoint_refs.length === 0) missing.add("checkpoint_refs");
  return [...missing];
}

function verificationRefs(state: WaygentRunStateV2): string[] {
  return state.verification
    .map((record) => typeof record.task_id === "string" ? `verification:${record.task_id}` : null)
    .filter((ref): ref is string => Boolean(ref));
}

function artifactRefs(state: WaygentRunStateV2): string[] {
  return (state.artifact_index ?? []).map((item) => item.ref);
}

function eventRefs(events: AgentLensEvent[]): string[] {
  return events.map((event) => `event:${event.event_id}`);
}

function rawRefs(evidence: OperatorEvidencePacket): string[] {
  return [...new Set([...evidence.event_refs, ...evidence.state_refs, ...evidence.artifact_refs])];
}

function priority(code: string): number {
  return blockerPriority.get(code) ?? 50;
}

function dedupeBlockers(blockers: OperatorBlocker[]): OperatorBlocker[] {
  const seen = new Set<string>();
  return blockers.filter((item) => {
    const key = `${item.code}:${item.task_id ?? "run"}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function dedupeActions(actions: OperatorAllowedAction[]): OperatorAllowedAction[] {
  const seen = new Set<string>();
  return actions.filter((action) => {
    if (seen.has(action.id)) return false;
    seen.add(action.id);
    return true;
  });
}

function labelForAction(id: OperatorActionId): string {
  return id.split("_").map((part) => part[0]!.toUpperCase() + part.slice(1)).join(" ");
}

function commandForAction(id: OperatorActionId, runId: string): string | null {
  if (id === "inspect_run") return `waygent inspect --run ${runId}`;
  if (id === "explain_run") return `waygent explain --run ${runId}`;
  if (id === "apply_run") return `waygent apply --run ${runId}`;
  if (id === "resume_run") return `waygent resume --run ${runId}`;
  return null;
}
```

- [ ] **Step 4: Export the projector**

Append to `packages/lens-projectors/src/index.ts`:

```ts
export * from "./operatorDecision";
```

- [ ] **Step 5: Run targeted projector tests and contract validation**

Run:

```bash
bun test packages/lens-projectors/tests/operatorDecision.test.ts packages/contracts/tests/contracts.test.ts
bun run typecheck
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit Task 2**

```bash
git add packages/lens-projectors/src/operatorDecision.ts packages/lens-projectors/src/index.ts packages/lens-projectors/tests/operatorDecision.test.ts
git commit -m "feat: project operator decisions from Waygent state"
```

## Task 3: Expose Operator Decision Through API And CLI

**Files:**

- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `apps/api/src/server.ts`
- Modify: `apps/api/tests/api.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`

- [ ] **Step 1: Write API parity test**

Append this test to `apps/api/tests/api.test.ts` before the route-not-found test:

```ts
  test("GET /runs/:runId exposes operator decision for real v2 runs", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-api-operator-decision-"));
    const runId = "run_operator_blocked";
    await runWaygentDemo({ root, run_id: runId, workspace: initSourceCheckout("waygent-api-source-") });
    const state = readRunStateV2(root, runId);
    writeRunStateV2(root, {
      ...state,
      status: "blocked",
      lifecycle_outcome: "blocked",
      current_phase: "recover",
      tasks: Object.fromEntries(
        Object.entries(state.tasks).map(([taskId, task]) => [taskId, {
          ...task,
          status: "blocked",
          checkpoint_refs: [],
          latest_failure_class: "verification_failed"
        }])
      ),
      verification: [{ verification_id: "verify_task_1", task_id: Object.keys(state.tasks)[0], command: "bun test", status: "failed" }],
      apply: { status: "blocked", reason: "verification_failed" },
      completion_audit: null
    });
    const realHandler = createApiHandler({ runRoot: root });

    const detailResponse = await realHandler(new Request(`http://waygent.local/runs/${runId}`));
    const detail = await detailResponse.json();
    const listResponse = await realHandler(new Request("http://waygent.local/runs"));
    const list = await listResponse.json();

    expect(detail.operator_decision).toMatchObject({
      schema: "waygent.operator_decision.v1",
      run_id: runId,
      primary_blocker: { code: "verification_failed" },
      status_summary: { display_status: "blocked", apply_status: "blocked" }
    });
    expect(detail.operator_decision.allowed_actions.map((action: { id: string }) => action.id)).toContain("open_ai_repair_handoff");
    expect(detail.operator_decision.blocked_actions.map((action: { id: string }) => action.id)).toContain("apply_run");
    expect(list.runs[0]).toMatchObject({
      run_id: runId,
      operator_status: "blocked",
      primary_blocker: "verification_failed",
      operator_confidence: "deterministic"
    });
  });
```

- [ ] **Step 2: Write CLI parity test**

Append this test to `apps/cli/tests/cli.test.ts` before `apply refuses a dirty source checkout...`:

```ts
  test("inspect and explain expose the shared operator decision", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-cli-operator-"));
    const runId = "run_cli_operator";
    await runCli(["run", "--provider", "fake", "--workspace", initSourceCheckout("waygent-cli-operator-source-"), "--root", root, "--run", runId]);
    const state = readRunStateV2(root, runId);
    const taskId = Object.keys(state.tasks)[0]!;
    writeFileSync(join(root, runId, "state.json"), JSON.stringify({
      ...state,
      status: "blocked",
      lifecycle_outcome: "blocked",
      current_phase: "recover",
      tasks: {
        ...state.tasks,
        [taskId]: {
          ...state.tasks[taskId],
          status: "blocked",
          checkpoint_refs: [],
          latest_failure_class: "needs_rebase"
        }
      },
      drift: {
        last_checked_at: "2026-05-22T00:00:00.000Z",
        records: [{ failure_class: "needs_rebase", files: ["README.md"] }],
        unrepaired_blockers: [{ failure_class: "needs_rebase", files: ["README.md"] }]
      },
      apply: { status: "blocked", reason: "needs_rebase" },
      completion_audit: null
    }, null, 2));

    const inspected = await runCli(["inspect", "--root", root, "--run", runId]) as {
      operator_decision: { primary_blocker: { code: string }; allowed_actions: Array<{ id: string }> };
    };
    const explained = await runCli(["explain", "--root", root, "--run", runId]) as {
      blocked_by: string | null;
      operator_decision: { primary_blocker: { code: string } };
    };

    expect(inspected.operator_decision.primary_blocker.code).toBe("needs_rebase");
    expect(inspected.operator_decision.allowed_actions.map((action) => action.id)).toContain("rebase_checkpoint");
    expect(explained.blocked_by).toBe("needs_rebase");
    expect(explained.operator_decision.primary_blocker.code).toBe("needs_rebase");
  });
```

- [ ] **Step 3: Run API and CLI tests and verify they fail for missing fields**

Run:

```bash
bun test apps/api/tests/api.test.ts apps/cli/tests/cli.test.ts
```

Expected: fail because `operator_decision` is absent.

- [ ] **Step 4: Update `inspectRun()` and `explainRun()`**

In `packages/orchestrator/src/runCommands.ts`:

1. Add `projectOperatorDecisionFromState` to the projector imports.
2. Add `operator_decision` to the `inspectRun()` return type.
3. Compute it in both v2 and state-error paths.
4. Make `explainRun()` derive `blocked_by` and summary from the same projection when v2 state exists.

Use this implementation shape:

```ts
const operatorDecision = projectOperatorDecisionFromState({
  state: stateResult.state,
  events,
  apply_readiness: projectApplyReadinessFromState(stateResult.state),
  execution_explanation: executionExplanation,
  operational_maturity: operationalMaturity
});
```

For state errors:

```ts
const operatorDecision = projectOperatorDecisionFromState({
  state: null,
  events,
  run_id: status.run_id,
  state_error: stateResult
});
```

In `explainRun()`, after computing the projection, return:

```ts
return {
  run_id: runId,
  blocked_by: operatorDecision.primary_blocker?.code as FailureClass | "unknown" | null,
  summary: operatorDecision.status_summary.summary,
  operator_decision: operatorDecision
};
```

Update the function return type to include `operator_decision`.

- [ ] **Step 5: Update API real run summaries and detail**

In `apps/api/src/server.ts`:

1. Import `OperatorDecisionProjection` and `projectOperatorDecisionFromState`.
2. Add to `RealRunSummary`:

```ts
  operator_status: string;
  primary_blocker: string | null;
  next_action: string | null;
  operator_confidence: string;
```

3. In `summarizeRealRun()`, compute the operator decision when v2 state exists:

```ts
  const operatorDecision = stateV2
    ? projectOperatorDecisionFromState({ state: stateV2, events })
    : projectOperatorDecisionFromState({
        state: null,
        events,
        run_id: runId,
        state_error: { status: "missing", reason: "missing_run_state_v2" }
      });
```

4. Return the summary fields:

```ts
    operator_status: operatorDecision.status_summary.display_status,
    primary_blocker: operatorDecision.primary_blocker?.code ?? null,
    next_action: operatorDecision.allowed_actions[0]?.id ?? null,
    operator_confidence: operatorDecision.confidence
```

5. Add `operator_decision: OperatorDecisionProjection` to `readRealRunDetail()` return type and return object. Reuse already computed `applyReadiness`, `executionExplanation`, and `operationalMaturity`:

```ts
  const operatorDecision = stateV2
    ? projectOperatorDecisionFromState({
        state: stateV2,
        events,
        apply_readiness: applyReadiness,
        execution_explanation: executionExplanation,
        operational_maturity: operationalMaturity
      })
    : projectOperatorDecisionFromState({
        state: null,
        events,
        run_id: runId,
        state_error: { status: "missing", reason: "missing_run_state_v2" }
      });
```

- [ ] **Step 6: Run targeted parity tests**

Run:

```bash
bun test apps/api/tests/api.test.ts apps/cli/tests/cli.test.ts packages/lens-projectors/tests/operatorDecision.test.ts
bun run typecheck
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit Task 3**

```bash
git add packages/orchestrator/src/runCommands.ts apps/api/src/server.ts apps/api/tests/api.test.ts apps/cli/tests/cli.test.ts
git commit -m "feat: expose operator decisions in API and CLI"
```

## Task 4: Add Workbench UI Model

**Files:**

- Modify: `apps/console/src/uiModel.ts`
- Modify: `apps/console/src/uiModel.test.ts`

- [ ] **Step 1: Write UI model tests**

Append these tests to `apps/console/src/uiModel.test.ts`:

```ts
  test("builds Workbench detail from operator decision projection", () => {
    const model = buildRunDetailModel({
      run_id: "run_workbench",
      status: "blocked",
      trust_status: "insufficient_evidence",
      apply_status: "blocked",
      total_events: 4,
      last_event_type: "runway.verification_result",
      safe_wave: [],
      failures: [],
      timeline: [
        { sequence: 1, phase: "platform", event_type: "platform.run_started", outcome: "running", summary: "Run opened." },
        { sequence: 2, phase: "runway", event_type: "runway.verification_result", outcome: "failed", summary: "Verification failed." }
      ],
      operator_decision: {
        schema: "waygent.operator_decision.v1",
        run_id: "run_workbench",
        generated_at: "2026-05-22T00:00:00.000Z",
        status_summary: {
          display_status: "blocked",
          runtime_status: "blocked",
          lifecycle_outcome: "blocked",
          current_phase: "recover",
          active_tasks: 0,
          completed_tasks: 0,
          blocked_tasks: 1,
          apply_status: "blocked",
          summary: "run_workbench is blocked by verification_failed."
        },
        primary_blocker: {
          code: "verification_failed",
          title: "Verification failed",
          summary: "task_a failed verification.",
          severity: "blocking",
          task_id: "task_a",
          evidence_refs: ["verification:task_a"],
          missing_refs: [],
          recommended_action_ids: ["rerun_verification", "open_ai_repair_handoff"]
        },
        secondary_blockers: [],
        allowed_actions: [
          { id: "inspect_run", label: "Inspect run", reason: "safe", evidence_refs: ["state:state.json"], requires_approval: false, requires_runtime_revalidation: false, command: "waygent inspect --run run_workbench" },
          { id: "open_ai_repair_handoff", label: "Open AI repair handoff", reason: "safe", evidence_refs: ["state:state.json"], requires_approval: false, requires_runtime_revalidation: false, command: null }
        ],
        blocked_actions: [
          { id: "apply_run", label: "Apply run", reason: "Apply readiness is blocked by verification_failed.", evidence_refs: ["verification:task_a"], unblocks_when: "Verification passes." }
        ],
        evidence_packet: {
          state_refs: ["state:state.json"],
          event_refs: ["events:events.jsonl"],
          artifact_refs: [],
          verification_refs: ["verification:task_a"],
          checkpoint_refs: [],
          projection_refs: ["waygent.execution_explanation.v1"],
          missing_refs: [],
          redaction_notes: []
        },
        ai_handoff: {
          purpose: "draft_repair_plan",
          prompt_summary: "Draft a repair plan for verification_failed using bounded evidence.",
          run_id: "run_workbench",
          current_status: "blocked",
          primary_blocker: "verification_failed",
          secondary_blockers: [],
          allowed_action_ids: ["inspect_run", "open_ai_repair_handoff"],
          blocked_action_ids: ["apply_run"],
          constraints: ["Do not apply patches."],
          evidence_refs: ["verification:task_a"],
          missing_evidence: [],
          raw_fallback_refs: ["events:events.jsonl"],
          safety_notes: ["Waygent runtime remains apply authority."]
        },
        confidence: "deterministic",
        unknown_reasons: [],
        source_projection_refs: {
          run_state_v2: "state:state.json",
          apply_readiness: "waygent.apply_readiness",
          execution_explanation: "waygent.execution_explanation.v1",
          operational_maturity: "waygent.operational_maturity.v1"
        }
      }
    });

    expect(model.operator_decision?.primary_blocker?.code).toBe("verification_failed");
    expect(model.outcome_strip).toMatchObject({
      display_status: "blocked",
      primary_blocker: "verification_failed",
      next_action: "inspect_run",
      apply_status: "blocked",
      confidence: "deterministic"
    });
    expect(model.operator_timeline.map((row) => row.row_type)).toEqual(["raw_event", "verification_result"]);
    expect(model.sections.map((section) => section.id)).toContain("operator-decision");
    expect(model.sections.map((section) => section.id)).toContain("ai-handoff");
    expect(model.raw_evidence_refs).toEqual(["state:state.json", "events:events.jsonl"]);
  });

  test("sorts run board by operator urgency", () => {
    const model = buildConsoleUiModel({
      generatedAt: "2026-05-22T00:00:00.000Z",
      runs: [
        { ...demoConsoleSnapshot.runs[0]!, runId: "run_done", title: "Done", status: "completed" },
        { ...demoConsoleSnapshot.runs[2]!, runId: "run_blocked", title: "Blocked", status: "blocked" },
        { ...demoConsoleSnapshot.runs[1]!, runId: "run_failed", title: "Failed", status: "failed" }
      ]
    });

    expect(model.runs.map((run) => run.runId)).toEqual(["run_blocked", "run_failed", "run_done"]);
  });
```

- [ ] **Step 2: Run UI model tests and verify they fail**

Run:

```bash
bun test apps/console/src/uiModel.test.ts
```

Expected: fail because `operator_decision`, `outcome_strip`, `operator_timeline`, and new section ids are absent.

- [ ] **Step 3: Add operator decision types to UI model**

In `apps/console/src/uiModel.ts`, import:

```ts
  OperatorDecisionProjection,
  OperatorTimelineRow,
```

from `@waygent/contracts`.

Add section ids:

```ts
  | "operator-decision"
  | "operator-timeline"
  | "ai-handoff"
  | "raw-evidence"
```

Add to `RealRunDetailResponse`:

```ts
  operator_decision?: OperatorDecisionProjection | null;
```

Add to `RunDetailModel`:

```ts
  operator_decision: OperatorDecisionProjection | null;
  outcome_strip: {
    display_status: string;
    primary_blocker: string | null;
    next_action: string | null;
    apply_status: string;
    confidence: string;
    summary: string;
  };
  operator_timeline: OperatorTimelineRow[];
  raw_evidence_refs: string[];
```

- [ ] **Step 4: Implement Workbench model helpers**

Add these helpers near the existing UI model helper functions:

```ts
function outcomeStripFromDecision(response: RealRunDetailResponse): RunDetailModel["outcome_strip"] {
  const decision = response.operator_decision ?? null;
  return {
    display_status: decision?.status_summary.display_status ?? response.status,
    primary_blocker: decision?.primary_blocker?.code ?? null,
    next_action: decision?.allowed_actions[0]?.id ?? null,
    apply_status: decision?.status_summary.apply_status ?? response.apply_status,
    confidence: decision?.confidence ?? "unknown",
    summary: decision?.status_summary.summary ?? `${response.run_id} has no operator decision projection.`
  };
}

function operatorTimelineFromResponse(response: RealRunDetailResponse): OperatorTimelineRow[] {
  return response.timeline.map((event, index) => ({
    id: `${response.run_id}:${event.sequence}:${event.event_type}`,
    sequence: event.sequence,
    timestamp: null,
    actor: event.event_type.split(".")[0] ?? "unknown",
    row_type: timelineRowType(event.event_type),
    title: event.event_type,
    outcome: consoleOutcome(event.outcome),
    severity: event.outcome === "failed" ? "error" : event.outcome === "blocked" ? "warning" : "info",
    task_id: null,
    evidence_refs: response.operator_decision?.evidence_packet.event_refs.slice(index, index + 1) ?? [],
    metadata: { phase: event.phase, summary: event.summary }
  }));
}

function timelineRowType(eventType: string): OperatorTimelineRow["row_type"] {
  if (eventType.includes("safe_wave")) return "safe_wave";
  if (eventType.includes("task_packet")) return "task_packet";
  if (eventType.includes("provider_attempt")) return "provider_attempt";
  if (eventType.includes("worker_result")) return "worker_result";
  if (eventType.includes("verification")) return "verification_result";
  if (eventType.includes("checkpoint")) return "checkpoint";
  if (eventType.includes("review")) return "review_finding";
  if (eventType.includes("recovery")) return "recovery_decision";
  if (eventType.includes("apply")) return "apply_readiness";
  return "raw_event";
}

function rawEvidenceRefs(decision: OperatorDecisionProjection | null): string[] {
  if (!decision) return [];
  return [...new Set([
    ...decision.evidence_packet.state_refs,
    ...decision.evidence_packet.event_refs,
    ...decision.evidence_packet.artifact_refs,
    ...decision.evidence_packet.verification_refs,
    ...decision.evidence_packet.checkpoint_refs
  ])];
}

function urgencyWeight(run: ConsoleRun): number {
  if (run.status === "blocked") return 0;
  if (run.status === "failed") return 3;
  if (run.applyStatus.state === "ready") return 4;
  return 5;
}
```

In `buildRunDetailModel()`, add:

```ts
    operator_decision: response.operator_decision ?? null,
    outcome_strip: outcomeStripFromDecision(response),
    operator_timeline: operatorTimelineFromResponse(response),
    raw_evidence_refs: rawEvidenceRefs(response.operator_decision ?? null),
```

Add the new sections before older supporting sections:

```ts
      { id: "operator-decision", label: "Operator decision" },
      { id: "operator-timeline", label: "Operator timeline" },
      { id: "ai-handoff", label: "AI handoff" },
      { id: "raw-evidence", label: "Raw evidence" },
```

In `buildConsoleUiModel()`, sort copied runs by urgency:

```ts
  const runs = [...snapshot.runs].sort((left, right) => urgencyWeight(left) - urgencyWeight(right));
```

Use `runs` for `firstRun`, `selectedRun`, and return value.

- [ ] **Step 5: Run Console model tests and typecheck**

Run:

```bash
bun test apps/console/src/uiModel.test.ts
bun run typecheck
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit Task 4**

```bash
git add apps/console/src/uiModel.ts apps/console/src/uiModel.test.ts
git commit -m "feat: model Lens Workbench operator state"
```

## Task 5: Build Console Workbench Product Surface

**Files:**

- Modify: `apps/console/src/App.tsx`
- Modify: `apps/console/src/styles.css`
- Modify: `apps/console/src/uiModel.test.ts` if render snapshot needs new text coverage

- [ ] **Step 1: Add render snapshot assertions**

Keep the existing `renders a text snapshot for browserless e2e checks` test unchanged. Add this separate blocked-run render test after it:

```ts
  test("renders blocked Workbench decision text for browserless checks", () => {
    const snapshot = renderConsoleSnapshot(
      buildConsoleUiModel(demoConsoleSnapshot, "run_demo_blocked")
    );

    expect(snapshot).toContain("run_demo_blocked");
    expect(snapshot).toContain("decision:");
    expect(snapshot).toContain("verification_failed");
    expect(snapshot).toContain("allowed: rerun_verification, update_plan");
    expect(snapshot).toContain("apply: blocked dirty_source_checkout");
  });
```

- [ ] **Step 2: Create Workbench components in App**

In `apps/console/src/App.tsx`, add these components above `App()`:

```tsx
function OutcomeStrip({ detail }: { detail: RunDetailModel }) {
  const outcome = detail.outcome_strip;
  return (
    <section className="outcome-strip" aria-label="Operator outcome">
      <div>
        <span>Status</span>
        <strong>{outcome.display_status}</strong>
      </div>
      <div>
        <span>Primary blocker</span>
        <strong>{outcome.primary_blocker ?? "none"}</strong>
      </div>
      <div>
        <span>Next action</span>
        <strong>{outcome.next_action ?? "inspect_run"}</strong>
      </div>
      <div>
        <span>Apply</span>
        <strong>{outcome.apply_status}</strong>
      </div>
      <div>
        <span>Confidence</span>
        <strong>{outcome.confidence}</strong>
      </div>
      <p>{outcome.summary}</p>
    </section>
  );
}

function OperatorTimeline({ detail }: { detail: RunDetailModel }) {
  return (
    <section className="operator-timeline" aria-label="Operator timeline">
      <div className="section-title-row">
        <h2>Operator Timeline</h2>
        <span>{detail.operator_timeline.length}</span>
      </div>
      <div className="timeline-controls" aria-label="Timeline filters">
        {["all", "blockers", "verification", "checkpoint", "provider", "apply", "recovery", "raw"].map((filter) => (
          <button type="button" key={filter}>{filter}</button>
        ))}
      </div>
      <div className="operator-rows">
        {detail.operator_timeline.map((row) => (
          <article className={`operator-row ${row.severity}`} key={row.id}>
            <span>{row.sequence}</span>
            <strong>{row.row_type}</strong>
            <p>{String(row.metadata.summary ?? row.title)}</p>
            <small>{row.evidence_refs.join(", ") || "no evidence ref"}</small>
          </article>
        ))}
      </div>
    </section>
  );
}

function DecisionRail({ detail }: { detail: RunDetailModel }) {
  const decision = detail.operator_decision;
  return (
    <aside className="decision-rail" aria-label="Decision and evidence rail">
      <section>
        <h2>Operator Decision</h2>
        <strong>{decision?.primary_blocker?.code ?? "none"}</strong>
        <p>{decision?.primary_blocker?.summary ?? detail.outcome_strip.summary}</p>
      </section>
      <section>
        <h3>Allowed Actions</h3>
        {(decision?.allowed_actions ?? []).map((action) => (
          <button className="rail-action" key={action.id} type="button">
            <span>{action.label}</span>
            <small>{action.reason}</small>
          </button>
        ))}
      </section>
      <section>
        <h3>Blocked Actions</h3>
        {(decision?.blocked_actions ?? []).map((action) => (
          <button className="rail-action disabled" disabled key={action.id} type="button">
            <span>{action.label}</span>
            <small>{action.reason}</small>
          </button>
        ))}
      </section>
      <section>
        <h3>AI Handoff</h3>
        <p>{decision?.ai_handoff.prompt_summary ?? "No AI handoff projection"}</p>
        <code>{decision?.ai_handoff.evidence_refs.join(", ") ?? "no evidence refs"}</code>
      </section>
      <section>
        <h3>Raw Evidence</h3>
        {detail.raw_evidence_refs.length === 0 ? (
          <p className="empty-state">No raw evidence refs</p>
        ) : (
          <ul>
            {detail.raw_evidence_refs.map((ref) => <li key={ref}>{ref}</li>)}
          </ul>
        )}
      </section>
    </aside>
  );
}
```

- [ ] **Step 3: Render the Workbench layout**

In the `App()` return, inside `.console-grid`, replace the current `.detail-surface` content order with:

```tsx
        <div className="workbench-surface">
          <OutcomeStrip detail={detail} />
          <div className="workbench-main">
            <div className="workbench-center">
              <OperatorTimeline detail={detail} />
              <OperationalMaturity detail={detail} />
              <ExecutionIntelligence detail={detail} />
              <OperationalEvidence detail={detail} />
            </div>
            <DecisionRail detail={detail} />
          </div>
        </div>
```

Do not render `TaskTimeline`, `EventTimeline`, `TrustReport`, `FailureBarriers`, `DecisionPackets`, or `ApplyStatus` in the first viewport. Keep those component functions in the file for now, but the rendered first viewport must show Run Board, Outcome Strip, Operator Timeline, and Decision Rail.

- [ ] **Step 4: Update run list rows**

In `RunList`, add visible operator hints:

```tsx
              <small>{run.applyStatus.state} · {run.applyStatus.reason}</small>
```

Keep the status dot and trust verdict. Long text must wrap inside the row.

- [ ] **Step 5: Replace CSS layout with Workbench structure**

In `apps/console/src/styles.css`, add these classes and adjust existing `.console-grid` widths:

```css
.console-grid {
  display: grid;
  grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.workbench-surface {
  min-width: 0;
  display: grid;
  gap: 12px;
}

.outcome-strip {
  position: sticky;
  top: 0;
  z-index: 2;
  display: grid;
  grid-template-columns: repeat(5, minmax(110px, 1fr));
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line, #d8dee8);
  background: var(--panel, #ffffff);
}

.outcome-strip p {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--text-muted, #5f6b7a);
}

.workbench-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 420px);
  gap: 12px;
  align-items: start;
}

.workbench-center {
  min-width: 0;
  display: grid;
  gap: 12px;
}

.operator-timeline,
.decision-rail {
  border: 1px solid var(--line, #d8dee8);
  background: var(--panel, #ffffff);
  padding: 12px;
}

.timeline-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.timeline-controls button {
  min-height: 30px;
}

.operator-rows {
  display: grid;
  gap: 8px;
}

.operator-row {
  display: grid;
  grid-template-columns: 48px 150px minmax(0, 1fr);
  gap: 8px;
  min-height: 64px;
  padding: 10px;
  border: 1px solid var(--line, #d8dee8);
}

.operator-row small {
  grid-column: 3;
  overflow-wrap: anywhere;
  color: var(--text-muted, #5f6b7a);
}

.decision-rail {
  position: sticky;
  top: 92px;
  display: grid;
  gap: 12px;
}

.rail-action {
  width: 100%;
  min-height: 48px;
  display: grid;
  gap: 3px;
  text-align: left;
}

.rail-action.disabled {
  opacity: 0.68;
}

@media (max-width: 920px) {
  .console-grid,
  .workbench-main,
  .outcome-strip {
    grid-template-columns: 1fr;
  }

  .decision-rail {
    position: static;
  }

  .operator-row {
    grid-template-columns: 40px minmax(0, 1fr);
  }

  .operator-row p,
  .operator-row small {
    grid-column: 2;
  }
}
```

After adding this, scan `styles.css` for unresolved variables. Replace undefined variables such as `--muted`, `--border`, or `--surface` with defined variables or fallback syntax `var(--name, #value)`.

- [ ] **Step 6: Run console tests and build**

Run:

```bash
bun test apps/console/src/uiModel.test.ts
cd apps/console && bun run build
```

Expected: both commands exit 0.

- [ ] **Step 7: Browser QA**

Start the local console with API data if available:

```bash
cd apps/console
bun run dev -- --port 5173
```

Open `http://127.0.0.1:5173` in the Codex in-app browser. Verify:

- first viewport shows run board, outcome strip, operator timeline, and decision rail;
- long blocker/action text wraps inside its container;
- disabled apply action shows the blocking reason;
- the layout works at desktop width and a narrow mobile-width viewport;
- no sections overlap;
- raw evidence refs remain visible.

Stop the dev server after QA.

- [ ] **Step 8: Commit Task 5**

```bash
git add apps/console/src/App.tsx apps/console/src/styles.css apps/console/src/uiModel.test.ts
git commit -m "feat: build Lens Workbench console surface"
```

## Task 6: Full Verification, Graphify, Review, Commit

**Files:**

- Modify: `graphify-out/GRAPH_REPORT.md`
- Modify: `graphify-out/graph.json`
- Read: `code_review.md`

- [ ] **Step 1: Run targeted tests**

Run:

```bash
bun test \
  packages/contracts/tests/contracts.test.ts \
  packages/lens-projectors/tests/operatorDecision.test.ts \
  apps/api/tests/api.test.ts \
  apps/cli/tests/cli.test.ts \
  apps/console/src/uiModel.test.ts
```

Expected: exit 0.

- [ ] **Step 2: Run full TypeScript and test suite**

Run:

```bash
bun run check
```

Expected: exit 0.

- [ ] **Step 3: Build console**

Run:

```bash
cd apps/console && bun run build
```

Expected: exit 0 and Vite emits a production build.

- [ ] **Step 4: Run patch hygiene**

Run from repo root:

```bash
git diff --check
```

Expected: no output and exit 0.

- [ ] **Step 5: Refresh Graphify**

Run:

```bash
graphify update .
```

Expected: `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.json` update and include `operatorDecision.ts` plus this plan/spec path.

- [ ] **Step 6: Read review checklist and perform focused self-review**

Run:

```bash
sed -n '1,260p' code_review.md
```

Review these specific risks:

- Does any UI path allow `apply_run` when `apply_readiness.status !== "ready"`?
- Does AI handoff ever tell an agent to mutate source or override runtime policy?
- Do API, CLI, and Console read the same `operator_decision` projection?
- Are state-missing and invalid-state cases explicit instead of silently inferred from events?
- Are legacy Python AgentLens, KWS CPE, and KWS CME absent from active routing?

- [ ] **Step 7: Final status and commit**

Run:

```bash
git status --short --branch --untracked-files=all
git add -A -- . ':(exclude)**/.DS_Store'
git status --short
git commit -m "feat: add Lens Workbench operator loop"
git status --short --branch --untracked-files=all
```

Expected:

- only intended files are staged before commit;
- no `.DS_Store` is staged;
- final status is clean except branch ahead count.

## Acceptance Checklist

- [ ] `waygent.operator_decision.v1` validates with AJV and rejects extra fields.
- [ ] Projector chooses one deterministic `primary_blocker` and preserves `secondary_blockers`.
- [ ] Missing state produces `confidence: "unknown"` and blocks unsafe actions.
- [ ] Missing evidence produces `confidence: "partial"` and lists `evidence_packet.missing_refs`.
- [ ] `apply_run` is allowed only when apply readiness is `ready` and no primary blocker exists.
- [ ] API run detail includes `operator_decision`.
- [ ] API run list includes operator status, primary blocker, next action, and confidence.
- [ ] CLI `inspect` returns `operator_decision`.
- [ ] CLI `explain` uses the same primary blocker as `operator_decision`.
- [ ] Console first viewport shows Run Board, Outcome Strip, Operator Timeline, and Decision/Evidence Rail.
- [ ] AI handoff contains bounded evidence refs and non-mutation constraints.
- [ ] Raw evidence refs remain visible.
- [ ] Browser QA confirms desktop and narrow layouts without overlap.
- [ ] `bun run check` passes.
- [ ] `cd apps/console && bun run build` passes.
- [ ] `git diff --check` passes.
- [ ] `graphify update .` has been run after source changes.
