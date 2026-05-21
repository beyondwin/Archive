# Waygent Operational Maturity Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one Waygent operator maturity loop that exposes dogfood evidence, runtime cost, and live-provider readiness through shared projections, CLI inspect/explain, API, console, deterministic dogfood checks, and docs.

**Architecture:** Keep `waygent.run_state.v2` as the runtime source of truth and add pure read-only projection modules in `packages/lens-projectors`. Wire those projections outward through `packages/orchestrator/src/runCommands.ts`, `apps/api/src/server.ts`, and `apps/console/src/uiModel.ts` / `App.tsx`, while keeping apply readiness owned by the existing completion-audit, checkpoint, combined-patch, reconciliation, and clean-checkout gates.

**Tech Stack:** Bun, TypeScript, React, Vite, `bun:test`, Waygent contracts, Waygent lens projectors, Waygent orchestrator, Graphify.

---

## Context

Design spec: `docs/superpowers/specs/2026-05-22-waygent-operational-maturity-loop-design.md`

Current anchors:

- `packages/contracts/src/types.ts` already defines `ExecutionExplanationProjection`, `ProviderLogSummary`, `ProviderAttempt`, `WaygentRunStateV2`, and `ApplyReadinessProjection`.
- `packages/lens-projectors/src/executionExplanation.ts` already computes safe-wave barriers, cost hotspots, artifact health, and first-pass recommendations.
- `packages/orchestrator/src/runCommands.ts` already returns `execution_explanation` from `inspectRun` and uses it in `explainRun`.
- `apps/api/src/server.ts` already includes `execution_explanation` in real run detail.
- `apps/console/src/uiModel.ts` and `apps/console/src/App.tsx` already render execution intelligence and provider stderr summaries.

Out of scope:

- Do not change apply readiness rules.
- Do not add live provider checks to default verification.
- Do not revive AgentRunway, KWS CPE, or KWS CME routing.
- Do not auto-rewrite plans from recommendations.

## File Structure

- `packages/contracts/src/types.ts`: add projection interfaces for dogfood evidence, runtime cost, provider readiness, and combined operational maturity.
- `packages/lens-projectors/src/dogfoodEvidence.ts`: pure dogfood evidence checklist projection from v2 state, events, apply readiness, and explain summary.
- `packages/lens-projectors/src/runtimeCost.ts`: pure runtime cost and plan-feedback projection from v2 state and execution explanation.
- `packages/lens-projectors/src/providerReadiness.ts`: pure provider readiness projection from provider profile and provider attempts.
- `packages/lens-projectors/src/operationalMaturity.ts`: pure composition of the three projections and top operator action.
- `packages/lens-projectors/src/index.ts`: export new projectors.
- `packages/lens-projectors/tests/operationalMaturity.test.ts`: projector unit tests.
- `packages/orchestrator/src/runCommands.ts`: attach maturity projections to `inspectRun` and use them in `explainRun`.
- `packages/orchestrator/tests/runCommandsV2.test.ts`: CLI-level projector and explain behavior tests.
- `apps/api/src/server.ts`: include maturity projection fields in real run detail responses.
- `apps/api/tests/api.test.ts`: API real-run response tests.
- `apps/console/src/uiModel.ts`: model maturity fields and next action.
- `apps/console/src/uiModel.test.ts`: model tests for maturity fields and apply-readiness isolation.
- `apps/console/src/App.tsx`: render a compact operational maturity section.
- `apps/console/src/styles.css`: add dense operator styling for the new section.
- `packages/testkit/src/waygentDogfood.ts`: deterministic dogfood evidence helper.
- `packages/testkit/src/index.ts`: export dogfood helper.
- `tests/integration/waygent-dogfood-evidence.test.ts`: fake-provider dogfood integration gate.
- `package.json`: make `waygent:dogfood` run the dogfood evidence gate.
- `docs/operations/waygent.md`, `docs/architecture/waygent.md`, `docs/operations/verification.md`: document the loop and verification command.
- `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`: refresh after code and docs structure changes.

## Waygent Task Packet

```yaml waygent-task
id: task_waygent_operational_maturity_loop
title: Implement Waygent Operational Maturity Loop
dependencies: []
file_claims:
  - path: packages/contracts/src/types.ts
    mode: owned
  - path: packages/lens-projectors/src/dogfoodEvidence.ts
    mode: owned
  - path: packages/lens-projectors/src/runtimeCost.ts
    mode: owned
  - path: packages/lens-projectors/src/providerReadiness.ts
    mode: owned
  - path: packages/lens-projectors/src/operationalMaturity.ts
    mode: owned
  - path: packages/lens-projectors/src/index.ts
    mode: owned
  - path: packages/lens-projectors/tests/operationalMaturity.test.ts
    mode: owned
  - path: packages/orchestrator/src/runCommands.ts
    mode: owned
  - path: packages/orchestrator/tests/runCommandsV2.test.ts
    mode: owned
  - path: apps/api/src/server.ts
    mode: owned
  - path: apps/api/tests/api.test.ts
    mode: owned
  - path: apps/console/src/uiModel.ts
    mode: owned
  - path: apps/console/src/uiModel.test.ts
    mode: owned
  - path: apps/console/src/App.tsx
    mode: owned
  - path: apps/console/src/styles.css
    mode: owned
  - path: packages/testkit/src/waygentDogfood.ts
    mode: owned
  - path: packages/testkit/src/index.ts
    mode: owned
  - path: tests/integration/waygent-dogfood-evidence.test.ts
    mode: owned
  - path: package.json
    mode: owned
  - path: docs/operations/waygent.md
    mode: owned
  - path: docs/operations/verification.md
    mode: owned
  - path: docs/architecture/waygent.md
    mode: owned
  - path: graphify-out/GRAPH_REPORT.md
    mode: owned
  - path: graphify-out/graph.json
    mode: owned
risk: medium
verify:
  - bun run check
  - bun run platform:demo
  - bun run waygent:scenarios
  - bun run waygent:dogfood
  - bun run check:legacy
  - bun run --cwd apps/console build
  - git diff --check
```

## Task Breakdown

```yaml
id: task_projection_contracts
title: Add operational maturity projection contracts and pure projectors
owner_boundary: packages/contracts and packages/lens-projectors
files:
  - path: packages/contracts/src/types.ts
    mode: edit
  - path: packages/lens-projectors/src/dogfoodEvidence.ts
    mode: owned
  - path: packages/lens-projectors/src/runtimeCost.ts
    mode: owned
  - path: packages/lens-projectors/src/providerReadiness.ts
    mode: owned
  - path: packages/lens-projectors/src/operationalMaturity.ts
    mode: owned
  - path: packages/lens-projectors/src/index.ts
    mode: edit
  - path: packages/lens-projectors/tests/operationalMaturity.test.ts
    mode: owned
acceptance:
  - command: bun test packages/lens-projectors/tests/operationalMaturity.test.ts packages/lens-projectors/tests/executionExplanation.test.ts
  - expected: PASS
risks:
  - Projection shape drift can make CLI/API/console compute different answers. Keep all maturity fields in lens-projectors and export from one place.
```

### Task 1: Add Operational Maturity Projection Contracts

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Create: `packages/lens-projectors/src/dogfoodEvidence.ts`
- Create: `packages/lens-projectors/src/runtimeCost.ts`
- Create: `packages/lens-projectors/src/providerReadiness.ts`
- Create: `packages/lens-projectors/src/operationalMaturity.ts`
- Modify: `packages/lens-projectors/src/index.ts`
- Create: `packages/lens-projectors/tests/operationalMaturity.test.ts`

- [ ] **Step 1: Write failing projector tests**

Create `packages/lens-projectors/tests/operationalMaturity.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import type { AgentLensEvent, WaygentRunStateV2 } from "@waygent/contracts";
import {
  projectDogfoodEvidenceFromState,
  projectOperationalMaturityFromState,
  projectProviderReadinessFromState,
  projectRuntimeCostFromState
} from "../src";

describe("operational maturity projectors", () => {
  test("projects complete dogfood evidence, runtime cost, and fake-provider readiness", () => {
    const state = makeState({
      artifact_index: [
        artifact("artifacts/provider/attempt_task_a_1.stdout.txt", "provider", "task_a"),
        artifact("artifacts/kernel/verify_task_a_1.json", "verification", "task_a"),
        artifact("artifacts/checkpoints/task_a/candidate_task_a.json", "checkpoint", "task_a"),
        artifact("artifacts/checkpoints/apply/run_demo.patch", "combined_apply", null)
      ],
      safe_waves: [
        {
          wave_id: "wave_1",
          ready: ["task_a"],
          concurrency: 1,
          timing: {
            started: "2026-05-22T00:00:00.000Z",
            completed: "2026-05-22T00:00:04.000Z",
            duration_ms: 4000
          },
          withheld: [{ task_id: "task_b", reason: "file_claim_conflict", detail: "README.md is already claimed" }]
        }
      ],
      tasks: {
        task_a: task("task_a", {
          phase_timings: [
            { phase: "provider", started: "2026-05-22T00:00:00.000Z", completed: "2026-05-22T00:00:01.000Z", duration_ms: 1000 },
            { phase: "verification", started: "2026-05-22T00:00:01.000Z", completed: "2026-05-22T00:00:03.000Z", duration_ms: 2000 },
            { phase: "checkpoint", started: "2026-05-22T00:00:03.000Z", completed: "2026-05-22T00:00:04.000Z", duration_ms: 1000 },
            { phase: "total", started: "2026-05-22T00:00:00.000Z", completed: "2026-05-22T00:00:04.000Z", duration_ms: 4000 }
          ]
        }),
        task_b: task("task_b", { status: "pending", checkpoint_refs: [] })
      },
      provider_attempts: [
        {
          schema: "runway.provider_attempt.v1",
          attempt_id: "attempt_task_a_1",
          run_id: "run_demo",
          task_id: "task_a",
          role: "implement",
          provider: "fake",
          command: ["fake-provider"],
          cwd: "/tmp/worktree",
          stdin_ref: "artifacts/provider/attempt_task_a_1.stdin.txt",
          stdout_ref: "artifacts/provider/attempt_task_a_1.stdout.txt",
          stderr_ref: "artifacts/provider/attempt_task_a_1.stderr.txt",
          event_stream_ref: null,
          exit_code: 0,
          timed_out: false,
          started_at: "2026-05-22T00:00:00.000Z",
          completed_at: "2026-05-22T00:00:01.000Z",
          worker_result_ref: "artifacts/worker/task_a.json",
          failure_class: null,
          process: {
            stdout: "{}",
            stderr: "",
            exit_code: 0,
            timed_out: false,
            started_at: "2026-05-22T00:00:00.000Z",
            completed_at: "2026-05-22T00:00:01.000Z",
            event_stream: null
          }
        }
      ],
      verification: [{ task_id: "task_a", verification_id: "verify_task_a_1", status: "passed" }],
      completion_audit: {
        status: "passed",
        combined_apply_evidence: {
          status: "passed",
          checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
          patch_ref: "artifacts/checkpoints/apply/run_demo.patch"
        }
      }
    });
    const events = [
      event(1, "platform.run_started", "2026-05-22T00:00:00.001Z"),
      event(2, "runway.worker_result", "2026-05-22T00:00:01.001Z"),
      event(3, "runway.verification_result", "2026-05-22T00:00:03.001Z"),
      event(4, "lens.trust_report_updated", "2026-05-22T00:00:04.001Z")
    ];

    expect(projectDogfoodEvidenceFromState({
      state,
      events,
      explain_summary: "no active failure barrier; cost hotspot: total 4000ms"
    })).toMatchObject({
      schema: "waygent.dogfood_evidence.v1",
      run_id: "run_demo",
      status: "complete"
    });
    expect(projectRuntimeCostFromState(state)).toMatchObject({
      schema: "waygent.runtime_cost.v1",
      estimated_waves: 1,
      measured_waves: 1,
      serial_barriers: [{ task_id: "task_b", reason: "file_claim_conflict", category: "file_claim" }]
    });
    expect(projectProviderReadinessFromState(state)).toMatchObject({
      schema: "waygent.provider_readiness.v1",
      run_id: "run_demo",
      provider: "fake",
      status: "ready"
    });
    expect(projectOperationalMaturityFromState({
      state,
      events,
      explain_summary: "no active failure barrier; cost hotspot: total 4000ms"
    })).toMatchObject({
      schema: "waygent.operational_maturity.v1",
      run_id: "run_demo",
      dogfood_evidence: { status: "complete" },
      provider_readiness: { status: "ready" }
    });
  });

  test("marks dogfood evidence partial when artifact index and phase timings are missing", () => {
    const projection = projectDogfoodEvidenceFromState({
      state: makeState({ tasks: { task_a: task("task_a", { phase_timings: [] }) } }),
      events: [event(1, "platform.run_started", "2026-05-22T00:00:00.001Z")],
      explain_summary: "no active failure barrier"
    });

    expect(projection.status).toBe("partial");
    expect(projection.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "artifact_index", status: "missing" }),
        expect.objectContaining({ id: "phase_timings", status: "missing" })
      ])
    );
  });

  test("classifies unavailable and auth-gated live provider readiness from provider attempts", () => {
    expect(projectProviderReadinessFromState(makeState({
      provider_profile: { provider: "codex" },
      provider_attempts: [providerAttempt({
        failure_class: "adapter_crashed",
        process: processEvidence("codex failed to start: spawn codex ENOENT")
      })]
    }))).toMatchObject({ status: "unavailable", recommended_next_action: "Install or expose the codex CLI before retrying." });

    expect(projectProviderReadinessFromState(makeState({
      provider_profile: { provider: "claude" },
      provider_attempts: [providerAttempt({
        failure_class: "adapter_crashed",
        process: processEvidence("Claude authentication required. Run claude login.")
      })]
    }))).toMatchObject({ status: "auth_required", recommended_next_action: "Authenticate the claude CLI before retrying live provider execution." });
  });
});

function artifact(ref: string, producer_phase: string, task_id: string | null) {
  return {
    ref,
    media_type: ref.endsWith(".json") ? "application/json" : "text/plain",
    sha256: "a".repeat(64),
    byte_length: 12,
    producer_phase: producer_phase as any,
    task_id,
    created_at: "2026-05-22T00:00:00.000Z"
  };
}

function event(sequence: number, event_type: string, occurred_at: string): AgentLensEvent {
  return {
    schema: "agentlens.event.v3",
    event_id: `event_run_demo_${sequence}`,
    agentlens_run_id: "run_demo",
    orchestrator_run_id: "run_demo",
    producer: { name: "waygent", kind: "orchestrator", version: "0.1.0" },
    event_type,
    occurred_at,
    sequence,
    phase: event_type.split(".")[0] ?? "platform",
    outcome: "success",
    severity: "info",
    trust_impact: "neutral",
    summary: event_type,
    payload: {}
  };
}

function providerAttempt(overrides: Partial<WaygentRunStateV2["provider_attempts"][number]>): WaygentRunStateV2["provider_attempts"][number] {
  return {
    schema: "runway.provider_attempt.v1",
    attempt_id: "attempt_task_a_1",
    run_id: "run_demo",
    task_id: "task_a",
    role: "implement",
    provider: "codex",
    command: ["codex", "exec", "--json", "-"],
    cwd: "/tmp/worktree",
    stdin_ref: "artifacts/provider/stdin.txt",
    stdout_ref: "artifacts/provider/stdout.txt",
    stderr_ref: "artifacts/provider/stderr.txt",
    event_stream_ref: null,
    exit_code: 1,
    timed_out: false,
    started_at: "2026-05-22T00:00:00.000Z",
    completed_at: "2026-05-22T00:00:01.000Z",
    worker_result_ref: "artifacts/worker/task_a.json",
    failure_class: "adapter_crashed",
    ...overrides
  };
}

function processEvidence(stderr: string): NonNullable<WaygentRunStateV2["provider_attempts"][number]["process"]> {
  return {
    stdout: "",
    stderr,
    exit_code: 1,
    timed_out: false,
    started_at: "2026-05-22T00:00:00.000Z",
    completed_at: "2026-05-22T00:00:01.000Z",
    event_stream: null
  };
}

function task(id: string, overrides: Partial<WaygentRunStateV2["tasks"][string]> = {}): WaygentRunStateV2["tasks"][string] {
  return {
    id,
    status: "verified",
    risk: "low",
    dependencies: [],
    file_claims: [{ path: `${id}.txt`, mode: "owned" }],
    attempts: ["attempt_task_a_1"],
    task_packet_path: `artifacts/task_packets/${id}.json`,
    task_packet_sha256: "b".repeat(64),
    unit_manifest: null,
    checkpoint_refs: [`artifacts/checkpoints/${id}/candidate_${id}.json`],
    latest_failure_class: null,
    decision_packet_ref: null,
    timing: {},
    phase_timings: [
      { phase: "provider", started: "2026-05-22T00:00:00.000Z", completed: "2026-05-22T00:00:01.000Z", duration_ms: 1000 },
      { phase: "verification", started: "2026-05-22T00:00:01.000Z", completed: "2026-05-22T00:00:02.000Z", duration_ms: 1000 },
      { phase: "total", started: "2026-05-22T00:00:00.000Z", completed: "2026-05-22T00:00:02.000Z", duration_ms: 2000 }
    ],
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

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
bun test packages/lens-projectors/tests/operationalMaturity.test.ts
```

Expected: FAIL with missing exports for `projectDogfoodEvidenceFromState`, `projectRuntimeCostFromState`, `projectProviderReadinessFromState`, and `projectOperationalMaturityFromState`.

- [ ] **Step 3: Add contract interfaces**

In `packages/contracts/src/types.ts`, after `ExecutionExplanationProjection`, add:

```ts
export type DogfoodEvidenceStatus = "complete" | "partial" | "missing" | "projection_error";
export type DogfoodEvidenceCheckStatus = "complete" | "partial" | "missing";

export interface DogfoodEvidenceCheck {
  id:
    | "event_journal"
    | "provider_attempts"
    | "verification_records"
    | "artifact_index"
    | "phase_timings"
    | "wave_timing"
    | "runtime_timestamps"
    | "explain_summary"
    | "readiness_artifacts";
  status: DogfoodEvidenceCheckStatus;
  summary: string;
  refs: string[];
}

export interface DogfoodEvidenceProjection {
  schema: "waygent.dogfood_evidence.v1";
  run_id: string;
  status: DogfoodEvidenceStatus;
  checks: DogfoodEvidenceCheck[];
  evidence_refs: string[];
  missing_reasons: string[];
  dogfood_run_ref: string | null;
}

export interface RuntimeCostProjection {
  schema: "waygent.runtime_cost.v1";
  run_id: string;
  estimated_waves: number;
  measured_waves: number;
  parallelism_score: number;
  serial_barriers: ExecutionBarrier[];
  measured: {
    tasks: Array<{ task_id: string; phase: ExecutionPhaseName; duration_ms: number }>;
    waves: Array<{ wave_id: string; concurrency: number | null; duration_ms: number }>;
  };
  hotspots: ExecutionCostHotspot[];
  recommended_next_actions: string[];
  dogfood: { status: DogfoodEvidenceStatus | "not_recorded"; evidence_refs: string[] };
}

export type ProviderReadinessStatus =
  | "ready"
  | "not_configured"
  | "unavailable"
  | "auth_required"
  | "failed"
  | "unknown";

export interface ProviderReadinessProjection {
  schema: "waygent.provider_readiness.v1";
  run_id: string;
  provider: string;
  status: ProviderReadinessStatus;
  command: string[];
  failure_class: FailureClass | string | null;
  timed_out: boolean;
  exit_code: number | null;
  stderr_summary: ProviderLogSummary | null;
  recommended_next_action: string;
}

export interface OperationalMaturityProjection {
  schema: "waygent.operational_maturity.v1";
  run_id: string;
  status: "healthy" | "attention" | "blocked";
  top_issue: string | null;
  next_action: string;
  dogfood_evidence: DogfoodEvidenceProjection;
  runtime_cost: RuntimeCostProjection;
  provider_readiness: ProviderReadinessProjection;
}
```

- [ ] **Step 4: Implement dogfood evidence projector**

Create `packages/lens-projectors/src/dogfoodEvidence.ts`:

```ts
import type {
  AgentLensEvent,
  ApplyReadinessProjection,
  DogfoodEvidenceCheck,
  DogfoodEvidenceProjection,
  DogfoodEvidenceStatus,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectApplyReadinessFromState } from "./apply";

export interface DogfoodEvidenceInput {
  state: WaygentRunStateV2;
  events: AgentLensEvent[];
  explain_summary?: string | null;
  dogfood_run_ref?: string | null;
}

export function projectDogfoodEvidenceFromState(input: DogfoodEvidenceInput): DogfoodEvidenceProjection {
  try {
    const applyReadiness = projectApplyReadinessFromState(input.state);
    const checks: DogfoodEvidenceCheck[] = [
      eventJournalCheck(input.events),
      providerAttemptCheck(input.state),
      verificationRecordCheck(input.state),
      artifactIndexCheck(input.state),
      phaseTimingCheck(input.state),
      waveTimingCheck(input.state),
      runtimeTimestampCheck(input.state, input.events),
      explainSummaryCheck(input.explain_summary ?? null),
      readinessArtifactCheck(applyReadiness)
    ];
    const missingReasons = checks
      .filter((check) => check.status === "missing")
      .map((check) => check.summary);
    const evidenceRefs = [...new Set(checks.flatMap((check) => check.refs))];
    return {
      schema: "waygent.dogfood_evidence.v1",
      run_id: input.state.run_id,
      status: statusFromChecks(checks),
      checks,
      evidence_refs: evidenceRefs,
      missing_reasons: missingReasons,
      dogfood_run_ref: input.dogfood_run_ref ?? null
    };
  } catch (error) {
    return {
      schema: "waygent.dogfood_evidence.v1",
      run_id: input.state.run_id,
      status: "projection_error",
      checks: [],
      evidence_refs: [],
      missing_reasons: [error instanceof Error ? error.message : String(error)],
      dogfood_run_ref: input.dogfood_run_ref ?? null
    };
  }
}

function eventJournalCheck(events: AgentLensEvent[]): DogfoodEvidenceCheck {
  return check("event_journal", events.length > 0, `${events.length} event journal record${events.length === 1 ? "" : "s"}`, []);
}

function providerAttemptCheck(state: WaygentRunStateV2): DogfoodEvidenceCheck {
  const refs = state.provider_attempts.flatMap((attempt) => [attempt.stdout_ref, attempt.stderr_ref, attempt.worker_result_ref].filter((ref): ref is string => typeof ref === "string" && ref.length > 0));
  return check("provider_attempts", state.provider_attempts.length > 0, `${state.provider_attempts.length} provider attempt${state.provider_attempts.length === 1 ? "" : "s"}`, refs);
}

function verificationRecordCheck(state: WaygentRunStateV2): DogfoodEvidenceCheck {
  const refs = state.verification
    .map((record) => record.kernel_result_ref)
    .filter((ref): ref is string => typeof ref === "string" && ref.length > 0);
  return check("verification_records", state.verification.length > 0, `${state.verification.length} verification record${state.verification.length === 1 ? "" : "s"}`, refs);
}

function artifactIndexCheck(state: WaygentRunStateV2): DogfoodEvidenceCheck {
  const refs = (state.artifact_index ?? []).map((entry) => entry.ref);
  return check("artifact_index", refs.length > 0, `${refs.length} indexed artifact${refs.length === 1 ? "" : "s"}`, refs);
}

function phaseTimingCheck(state: WaygentRunStateV2): DogfoodEvidenceCheck {
  const timings = Object.values(state.tasks).flatMap((task) => task.phase_timings ?? []);
  const hasProvider = timings.some((timing) => timing.phase === "provider");
  const hasVerification = timings.some((timing) => timing.phase === "verification");
  const hasTerminal = timings.some((timing) => timing.phase === "checkpoint" || timing.phase === "total");
  return check("phase_timings", hasProvider && hasVerification && hasTerminal, `${timings.length} task phase timing record${timings.length === 1 ? "" : "s"}`, []);
}

function waveTimingCheck(state: WaygentRunStateV2): DogfoodEvidenceCheck {
  const executedWaves = state.safe_waves.filter((wave) => wave.ready.length > 0);
  const measured = executedWaves.filter((wave) => typeof wave.timing?.duration_ms === "number" && typeof wave.concurrency === "number");
  return check("wave_timing", executedWaves.length === 0 || measured.length === executedWaves.length, `${measured.length}/${executedWaves.length} executed waves have timing and concurrency`, []);
}

function runtimeTimestampCheck(state: WaygentRunStateV2, events: AgentLensEvent[]): DogfoodEvidenceCheck {
  const eventTimestamps = events.map((event) => event.occurred_at).filter(Boolean);
  const uniqueEventTimestamps = new Set(eventTimestamps);
  const hasStateTimestamps = Boolean(state.timestamps.started_at && state.timestamps.updated_at);
  const hasEventTimestamps = eventTimestamps.length === 0 || uniqueEventTimestamps.size > 1;
  return check("runtime_timestamps", hasStateTimestamps && hasEventTimestamps, `${uniqueEventTimestamps.size} unique event timestamp${uniqueEventTimestamps.size === 1 ? "" : "s"}`, []);
}

function explainSummaryCheck(summary: string | null): DogfoodEvidenceCheck {
  const precise = Boolean(summary && (summary.includes("blocked by") || summary.includes("no active failure barrier")));
  return check("explain_summary", precise, summary ?? "missing explain summary", []);
}

function readinessArtifactCheck(readiness: ApplyReadinessProjection): DogfoodEvidenceCheck {
  if (readiness.status !== "ready") {
    return { id: "readiness_artifacts", status: "complete", summary: "apply readiness is not ready, so readiness refs are not required", refs: [] };
  }
  const refs = [...readiness.checkpoint_refs, readiness.combined_patch_ref].filter((ref): ref is string => typeof ref === "string" && ref.length > 0);
  return check("readiness_artifacts", refs.length > 0, `${refs.length} readiness artifact ref${refs.length === 1 ? "" : "s"}`, refs);
}

function check(id: DogfoodEvidenceCheck["id"], passed: boolean, summary: string, refs: string[]): DogfoodEvidenceCheck {
  return { id, status: passed ? "complete" : "missing", summary, refs };
}

function statusFromChecks(checks: DogfoodEvidenceCheck[]): DogfoodEvidenceStatus {
  if (checks.every((check) => check.status === "complete")) return "complete";
  if (checks.every((check) => check.status === "missing")) return "missing";
  return "partial";
}
```

- [ ] **Step 5: Implement runtime cost projector**

Create `packages/lens-projectors/src/runtimeCost.ts`:

```ts
import type {
  DogfoodEvidenceProjection,
  ExecutionBarrier,
  ExecutionCostHotspot,
  RuntimeCostProjection,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectExecutionExplanationFromState } from "./executionExplanation";

export function projectRuntimeCostFromState(
  state: WaygentRunStateV2,
  dogfood?: DogfoodEvidenceProjection
): RuntimeCostProjection {
  const explanation = projectExecutionExplanationFromState(state);
  const measuredTasks = Object.values(state.tasks).flatMap((task) =>
    (task.phase_timings ?? [])
      .filter((timing) => typeof timing.duration_ms === "number")
      .map((timing) => ({ task_id: task.id, phase: timing.phase, duration_ms: timing.duration_ms as number }))
  );
  const measuredWaves = state.safe_waves
    .filter((wave) => typeof wave.timing?.duration_ms === "number")
    .map((wave) => ({
      wave_id: wave.wave_id,
      concurrency: wave.concurrency ?? null,
      duration_ms: wave.timing!.duration_ms
    }));
  const estimatedWaves = Math.max(1, state.safe_waves.length);
  return {
    schema: "waygent.runtime_cost.v1",
    run_id: state.run_id,
    estimated_waves: estimatedWaves,
    measured_waves: measuredWaves.length,
    parallelism_score: parallelismScore(state),
    serial_barriers: explanation.barriers,
    measured: { tasks: measuredTasks, waves: measuredWaves },
    hotspots: explanation.cost_hotspots,
    recommended_next_actions: runtimeRecommendations(explanation.barriers, explanation.cost_hotspots, dogfood),
    dogfood: dogfood
      ? { status: dogfood.status, evidence_refs: dogfood.evidence_refs }
      : { status: "not_recorded", evidence_refs: [] }
  };
}

function parallelismScore(state: WaygentRunStateV2): number {
  const taskCount = Object.keys(state.tasks).length;
  if (taskCount === 0) return 0;
  const widestWave = Math.max(0, ...state.safe_waves.map((wave) => wave.ready.length));
  return Number((widestWave / taskCount).toFixed(2));
}

function runtimeRecommendations(
  barriers: ExecutionBarrier[],
  hotspots: ExecutionCostHotspot[],
  dogfood: DogfoodEvidenceProjection | undefined
): string[] {
  const result = new Set<string>();
  if (barriers.some((barrier) => barrier.category === "file_claim")) {
    result.add("Split overlapping owned file claims or add explicit dependencies before expecting wider safe waves.");
  }
  if (barriers.some((barrier) => barrier.category === "risk")) {
    result.add("Reduce high-risk task scope before expecting wider safe waves.");
  }
  if (barriers.some((barrier) => barrier.category === "dependency")) {
    result.add("Add dependency checkpoints explicitly so the scheduler can explain serial release.");
  }
  if (hotspots.some((hotspot) => hotspot.phase === "verification")) {
    result.add("Inspect verification commands and dependency setup before increasing provider concurrency.");
  }
  if (hotspots.some((hotspot) => hotspot.phase === "worktree_setup")) {
    result.add("Inspect worktree setup cost before changing provider concurrency.");
  }
  if (dogfood && dogfood.status !== "complete") {
    result.add("Run the dogfood evidence gate before treating execution intelligence as complete.");
  }
  if (result.size === 0) {
    result.add("No trust-preserving runtime optimization is recommended from the recorded evidence.");
  }
  return [...result];
}
```

- [ ] **Step 6: Implement provider readiness projector**

Create `packages/lens-projectors/src/providerReadiness.ts`:

```ts
import type {
  FailureClass,
  ProviderAttempt,
  ProviderReadinessProjection,
  ProviderReadinessStatus,
  WaygentRunStateV2
} from "@waygent/contracts";

export function projectProviderReadinessFromState(state: WaygentRunStateV2): ProviderReadinessProjection {
  const provider = providerName(state);
  const attempts = state.provider_attempts.filter((attempt) => attempt.provider === provider || provider === "fake");
  const latest = attempts.at(-1) ?? state.provider_attempts.at(-1) ?? null;
  const status = providerReadinessStatus(provider, latest);
  return {
    schema: "waygent.provider_readiness.v1",
    run_id: state.run_id,
    provider,
    status,
    command: latest?.command ?? providerCommand(provider),
    failure_class: latest?.failure_class ?? null,
    timed_out: latest?.timed_out ?? false,
    exit_code: latest?.exit_code ?? null,
    stderr_summary: latest?.process?.stderr_summary ?? null,
    recommended_next_action: readinessAction(provider, status, latest)
  };
}

function providerName(state: WaygentRunStateV2): string {
  const provider = state.provider_profile.provider;
  return typeof provider === "string" && provider.length > 0 ? provider : "unknown";
}

function providerCommand(provider: string): string[] {
  if (provider === "codex") return ["codex", "exec", "--json", "-"];
  if (provider === "claude") return ["claude", "-p", "--output-format", "json"];
  if (provider === "fake") return ["fake-provider"];
  return [];
}

function providerReadinessStatus(provider: string, attempt: ProviderAttempt | null): ProviderReadinessStatus {
  if (provider === "fake") return "ready";
  if (provider === "unknown") return "not_configured";
  if (!attempt) return "unknown";
  const stderr = attempt.process?.stderr ?? "";
  if (attempt.timed_out || attempt.failure_class === "timeout") return "failed";
  if (looksUnavailable(stderr)) return "unavailable";
  if (looksAuthRequired(stderr)) return "auth_required";
  if (attempt.failure_class === null && attempt.exit_code === 0) return "ready";
  return "failed";
}

function looksUnavailable(stderr: string): boolean {
  return /ENOENT|not found|command not found|failed to start|spawn .* ENOENT/i.test(stderr);
}

function looksAuthRequired(stderr: string): boolean {
  return /auth|authenticate|authenticated|login|sign in|permission denied/i.test(stderr);
}

function readinessAction(provider: string, status: ProviderReadinessStatus, attempt: ProviderAttempt | null): string {
  if (status === "ready") return provider === "fake" ? "Use fake provider for deterministic local verification." : `Run ${provider} live smoke only when cost and auth are acceptable.`;
  if (status === "not_configured") return "Select a provider before running live provider execution.";
  if (status === "unavailable") return `Install or expose the ${provider} CLI before retrying.`;
  if (status === "auth_required") return `Authenticate the ${provider} CLI before retrying live provider execution.`;
  if (attempt?.failure_class) return providerFailureAction(provider, attempt.failure_class);
  return "Inspect provider command configuration before retrying live execution.";
}

function providerFailureAction(provider: string, failureClass: FailureClass | string): string {
  if (failureClass === "malformed_result") return `Inspect ${provider} stdout and update provider result normalization or the worker prompt.`;
  if (failureClass === "timeout") return `Reduce task scope or increase the ${provider} timeout after inspecting partial output.`;
  if (failureClass === "adapter_crashed") return `Inspect ${provider} stderr before retrying or switching provider.`;
  return `Inspect ${provider} provider attempt evidence before retrying.`;
}
```

- [ ] **Step 7: Implement combined maturity projector and exports**

Create `packages/lens-projectors/src/operationalMaturity.ts`:

```ts
import type {
  AgentLensEvent,
  OperationalMaturityProjection,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectDogfoodEvidenceFromState } from "./dogfoodEvidence";
import { projectProviderReadinessFromState } from "./providerReadiness";
import { projectRuntimeCostFromState } from "./runtimeCost";

export interface OperationalMaturityInput {
  state: WaygentRunStateV2;
  events: AgentLensEvent[];
  explain_summary?: string | null;
  dogfood_run_ref?: string | null;
}

export function projectOperationalMaturityFromState(input: OperationalMaturityInput): OperationalMaturityProjection {
  const dogfood = projectDogfoodEvidenceFromState(input);
  const runtimeCost = projectRuntimeCostFromState(input.state, dogfood);
  const providerReadiness = projectProviderReadinessFromState(input.state);
  const topIssue = topIssue(input.state, dogfood.status, providerReadiness.status);
  return {
    schema: "waygent.operational_maturity.v1",
    run_id: input.state.run_id,
    status: input.state.status === "blocked" || input.state.status === "failed" ? "blocked" : dogfood.status === "complete" && providerReadiness.status === "ready" ? "healthy" : "attention",
    top_issue: topIssue,
    next_action: nextAction(topIssue, runtimeCost.recommended_next_actions[0], providerReadiness.recommended_next_action),
    dogfood_evidence: dogfood,
    runtime_cost: runtimeCost,
    provider_readiness: providerReadiness
  };
}

function topIssue(state: WaygentRunStateV2, dogfoodStatus: string, providerStatus: string): string | null {
  const blocked = Object.values(state.tasks).find((task) => typeof task.latest_failure_class === "string" && task.latest_failure_class.length > 0);
  if (blocked?.latest_failure_class) return `${blocked.id} blocked by ${blocked.latest_failure_class}`;
  if (state.drift.unrepaired_blockers.length > 0) return "run has unrepaired drift blockers";
  if (dogfoodStatus !== "complete") return `dogfood evidence is ${dogfoodStatus}`;
  if (providerStatus !== "ready") return `provider readiness is ${providerStatus}`;
  return null;
}

function nextAction(topIssue: string | null, runtimeAction: string | undefined, providerAction: string): string {
  if (topIssue?.includes("blocked by")) return "Run waygent explain before resume or apply.";
  if (topIssue?.includes("drift")) return "Repair drift or regenerate checkpoint evidence before apply.";
  if (topIssue?.includes("dogfood")) return "Run the dogfood evidence gate and inspect missing evidence.";
  if (topIssue?.includes("provider readiness")) return providerAction;
  return runtimeAction ?? "Inspect the run before changing provider concurrency or apply state.";
}
```

Modify `packages/lens-projectors/src/index.ts`:

```ts
export * from "./trust";
export * from "./apply";
export * from "./executionExplanation";
export * from "./dogfoodEvidence";
export * from "./runtimeCost";
export * from "./providerReadiness";
export * from "./operationalMaturity";
```

- [ ] **Step 8: Run projection tests**

Run:

```bash
bun test packages/lens-projectors/tests/operationalMaturity.test.ts packages/lens-projectors/tests/executionExplanation.test.ts
```

Expected: PASS.

- [ ] **Step 9: Commit projection contracts**

Run:

```bash
git add packages/contracts/src/types.ts \
  packages/lens-projectors/src/dogfoodEvidence.ts \
  packages/lens-projectors/src/runtimeCost.ts \
  packages/lens-projectors/src/providerReadiness.ts \
  packages/lens-projectors/src/operationalMaturity.ts \
  packages/lens-projectors/src/index.ts \
  packages/lens-projectors/tests/operationalMaturity.test.ts
git commit -m "feat: project Waygent operational maturity"
```

```yaml
id: task_cli_maturity
title: Attach maturity projections to inspect and explain
owner_boundary: packages/orchestrator CLI command model
files:
  - path: packages/orchestrator/src/runCommands.ts
    mode: edit
  - path: packages/orchestrator/tests/runCommandsV2.test.ts
    mode: edit
acceptance:
  - command: bun test packages/orchestrator/tests/runCommandsV2.test.ts
  - expected: PASS
risks:
  - explainRun can become noisy. Keep the summary ordered: hard blocker, scheduling barrier, cost hotspot, dogfood gap.
```

### Task 2: Attach Maturity Projections To CLI Inspect And Explain

**Files:**
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/orchestrator/tests/runCommandsV2.test.ts`

- [ ] **Step 1: Add failing run command tests**

Append to `packages/orchestrator/tests/runCommandsV2.test.ts`:

```ts
test("inspect includes operational maturity projections for v2 runs", () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-inspect-maturity-"));
  const runId = "run_maturity";
  writeRunStateV2(root, {
    schema: "waygent.run_state.v2",
    run_id: runId,
    workspace: root,
    source_branch: "main",
    worktree_root: join(root, "worktrees"),
    run_root: join(root, runId),
    artifact_root: join(root, runId, "artifacts"),
    state_path: runStatePath(root, runId),
    event_journal_path: join(root, runId, "events.jsonl"),
    plan_path: null,
    spec_path: null,
    provider_profile: { provider: "fake" },
    status: "completed",
    lifecycle_outcome: "finished",
    current_phase: "complete",
    safe_waves: [
      {
        wave_id: "wave_1",
        ready: ["task_maturity"],
        concurrency: 1,
        timing: {
          started: "2026-05-22T00:00:00.000Z",
          completed: "2026-05-22T00:00:02.000Z",
          duration_ms: 2000
        },
        withheld: []
      }
    ],
    tasks: {
      task_maturity: {
        id: "task_maturity",
        status: "verified",
        risk: "low",
        dependencies: [],
        file_claims: [{ path: "README.md", mode: "owned" }],
        attempts: ["attempt_task_maturity_1"],
        task_packet_path: "artifacts/task_packets/task_maturity.json",
        task_packet_sha256: "a".repeat(64),
        unit_manifest: null,
        checkpoint_refs: ["artifacts/checkpoints/task_maturity/candidate_task_maturity.json"],
        latest_failure_class: null,
        decision_packet_ref: null,
        timing: {},
        phase_timings: [
          { phase: "provider", started: "2026-05-22T00:00:00.000Z", completed: "2026-05-22T00:00:01.000Z", duration_ms: 1000 },
          { phase: "verification", started: "2026-05-22T00:00:01.000Z", completed: "2026-05-22T00:00:02.000Z", duration_ms: 1000 },
          { phase: "total", started: "2026-05-22T00:00:00.000Z", completed: "2026-05-22T00:00:02.000Z", duration_ms: 2000 }
        ]
      }
    },
    provider_attempts: [],
    reviews: [],
    verification: [{ task_id: "task_maturity", verification_id: "verify_task_maturity_1", status: "passed" }],
    recovery: [],
    apply: { status: "not_applied" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: null,
    artifact_index: [
      {
        ref: "artifacts/task_packets/task_maturity.json",
        media_type: "application/json",
        sha256: "a".repeat(64),
        byte_length: 10,
        producer_phase: "task_packet",
        task_id: "task_maturity",
        created_at: "2026-05-22T00:00:00.000Z"
      }
    ],
    timestamps: {
      started_at: "2026-05-22T00:00:00.000Z",
      updated_at: "2026-05-22T00:00:02.000Z",
      completed_at: "2026-05-22T00:00:02.000Z"
    }
  });
  appendEvent(join(root, runId, "events.jsonl"), buildRunEvent({
    run_id: runId,
    sequence: 1,
    event_type: "platform.run_started",
    phase: "platform",
    outcome: "running",
    summary: "Run opened.",
    payload: {},
    occurred_at: "2026-05-22T00:00:00.001Z"
  }));
  appendEvent(join(root, runId, "events.jsonl"), buildRunEvent({
    run_id: runId,
    sequence: 2,
    event_type: "lens.trust_report_updated",
    phase: "lens",
    outcome: "success",
    summary: "Trust report updated.",
    payload: {},
    occurred_at: "2026-05-22T00:00:02.001Z"
  }));

  const inspected = inspectRun({ root, run: runId });

  expect(inspected.operational_maturity).toMatchObject({
    schema: "waygent.operational_maturity.v1",
    run_id: runId
  });
  expect(inspected.runtime_cost).toMatchObject({
    schema: "waygent.runtime_cost.v1",
    measured_waves: 1
  });
  expect(inspected.provider_readiness).toMatchObject({
    schema: "waygent.provider_readiness.v1",
    status: "ready"
  });
});

test("explain reports dogfood evidence gaps after hard blockers and cost hotspots", () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-explain-maturity-"));
  const runId = "run_partial_dogfood";
  writeRunStateV2(root, {
    schema: "waygent.run_state.v2",
    run_id: runId,
    workspace: root,
    source_branch: "main",
    worktree_root: join(root, "worktrees"),
    run_root: join(root, runId),
    artifact_root: join(root, runId, "artifacts"),
    state_path: runStatePath(root, runId),
    event_journal_path: join(root, runId, "events.jsonl"),
    plan_path: null,
    spec_path: null,
    provider_profile: { provider: "fake" },
    status: "completed",
    lifecycle_outcome: "finished",
    current_phase: "complete",
    tasks: {
      task_partial: {
        id: "task_partial",
        status: "verified",
        risk: "low",
        dependencies: [],
        file_claims: [{ path: "README.md", mode: "owned" }],
        attempts: [],
        task_packet_path: null,
        task_packet_sha256: null,
        unit_manifest: null,
        checkpoint_refs: [],
        latest_failure_class: null,
        decision_packet_ref: null,
        timing: {}
      }
    },
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
      updated_at: "2026-05-22T00:00:01.000Z",
      completed_at: "2026-05-22T00:00:01.000Z"
    }
  });
  appendEvent(join(root, runId, "events.jsonl"), buildRunEvent({
    run_id: runId,
    sequence: 1,
    event_type: "platform.run_started",
    phase: "platform",
    outcome: "running",
    summary: "Run opened.",
    payload: {}
  }));

  expect(explainRun({ root, run: runId }).summary).toContain("dogfood evidence: partial");
});
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
bun test packages/orchestrator/tests/runCommandsV2.test.ts
```

Expected: FAIL because `inspectRun` does not include `operational_maturity`, `dogfood_evidence`, `runtime_cost`, or `provider_readiness`.

- [ ] **Step 3: Wire projections into runCommands**

In `packages/orchestrator/src/runCommands.ts`, update imports:

```ts
import {
  projectApplyReadinessFromState,
  projectDogfoodEvidenceFromState,
  projectExecutionExplanationFromState,
  projectFailureSummary,
  projectOperationalMaturityFromState,
  projectProviderReadinessFromState,
  projectRuntimeCostFromState,
  projectTrustReport
} from "@waygent/lens-projectors";
```

Update `inspectRun` return type:

```ts
export function inspectRun(options: RunCommandOptions): RunStatusView & {
  failures: ReturnType<typeof projectFailureSummary>;
  state?: WaygentRunStateV2;
  execution_explanation?: ReturnType<typeof projectExecutionExplanationFromState>;
  dogfood_evidence?: ReturnType<typeof projectDogfoodEvidenceFromState>;
  runtime_cost?: ReturnType<typeof projectRuntimeCostFromState>;
  provider_readiness?: ReturnType<typeof projectProviderReadinessFromState>;
  operational_maturity?: ReturnType<typeof projectOperationalMaturityFromState>;
  state_error?: Exclude<RunStateV2ReadResult, { status: "ok" }>;
}
```

Replace the successful v2 branch in `inspectRun` with:

```ts
const events = readEvents(runPaths(options.root, status.run_id).events);
const failures = projectFailureSummary(events);
const stateResult = readRunStateV2Result(options.root, status.run_id);
if (stateResult.status === "ok") {
  const explanation = projectExecutionExplanationFromState(stateResult.state);
  const explainSummary = explainSummaryForState(stateResult.state, failures[0] ?? null, explanation);
  const dogfood = projectDogfoodEvidenceFromState({ state: stateResult.state, events, explain_summary: explainSummary });
  const runtimeCost = projectRuntimeCostFromState(stateResult.state, dogfood);
  const providerReadiness = projectProviderReadinessFromState(stateResult.state);
  const operationalMaturity = projectOperationalMaturityFromState({
    state: stateResult.state,
    events,
    explain_summary: explainSummary
  });
  return {
    ...status,
    failures,
    state: stateResult.state,
    execution_explanation: explanation,
    dogfood_evidence: dogfood,
    runtime_cost: runtimeCost,
    provider_readiness: providerReadiness,
    operational_maturity: operationalMaturity
  };
}
return { ...status, failures, state_error: stateResult };
```

Add helper near `blockedTaskFailure`:

```ts
function explainSummaryForState(
  state: WaygentRunStateV2,
  failure: ReturnType<typeof projectFailureSummary>[number] | null,
  explanation: ReturnType<typeof projectExecutionExplanationFromState>
): string {
  const stateFailure = blockedTaskFailure(state);
  const activeFailure = stateFailure ?? failure;
  const barrier = explanation.barriers[0];
  const hotspot = explanation.cost_hotspots[0];
  const summaryParts = [
    activeFailure ? `${activeFailure.task_id} blocked by ${activeFailure.failure_class}` : "no active failure barrier",
    barrier ? `scheduling barrier: ${barrier.task_id} ${barrier.reason}` : null,
    hotspot ? `cost hotspot: ${hotspot.phase} ${hotspot.duration_ms}ms` : null
  ].filter(Boolean);
  return summaryParts.join("; ");
}
```

Replace the v2 branch in `explainRun` with:

```ts
if (stateResult.status === "ok") {
  const explanation = projectExecutionExplanationFromState(stateResult.state);
  const summary = explainSummaryForState(stateResult.state, failure, explanation);
  const dogfood = projectDogfoodEvidenceFromState({ state: stateResult.state, events, explain_summary: summary });
  const runtimeCost = projectRuntimeCostFromState(stateResult.state, dogfood);
  const stateFailure = blockedTaskFailure(stateResult.state);
  const activeFailure = stateFailure ?? failure;
  const dogfoodPart = dogfood.status !== "complete" ? `dogfood evidence: ${dogfood.status}` : null;
  const runtimePart = runtimeCost.hotspots[0] ? `runtime hotspot: ${runtimeCost.hotspots[0].phase} ${runtimeCost.hotspots[0].duration_ms}ms` : null;
  return {
    run_id: runId,
    blocked_by: activeFailure?.failure_class ?? null,
    summary: [summary, activeFailure ? null : runtimePart, activeFailure ? null : dogfoodPart].filter(Boolean).join("; ")
  };
}
```

- [ ] **Step 4: Run run command tests**

Run:

```bash
bun test packages/orchestrator/tests/runCommandsV2.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit CLI projection wiring**

Run:

```bash
git add packages/orchestrator/src/runCommands.ts packages/orchestrator/tests/runCommandsV2.test.ts
git commit -m "feat: expose Waygent maturity in inspect"
```

```yaml
id: task_api_maturity
title: Return maturity loop projections from real run API detail
owner_boundary: apps/api
files:
  - path: apps/api/src/server.ts
    mode: edit
  - path: apps/api/tests/api.test.ts
    mode: edit
acceptance:
  - command: bun test apps/api/tests/api.test.ts
  - expected: PASS
risks:
  - API detail can drift from CLI inspect. Compute from lens-projectors with the same inputs and keep aliases top-level for console.
```

### Task 3: Return Maturity Projections From API

**Files:**
- Modify: `apps/api/src/server.ts`
- Modify: `apps/api/tests/api.test.ts`

- [ ] **Step 1: Add failing API test**

In `apps/api/tests/api.test.ts`, add:

```ts
test("GET /runs/:runId exposes operational maturity projections for real v2 runs", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-api-maturity-"));
  const runId = "run_api_maturity";
  await runWaygentDemo({ root, run_id: runId, workspace: initSourceCheckout("waygent-api-maturity-source-") });
  const realHandler = createApiHandler({ runRoot: root });

  const response = await realHandler(new Request(`http://waygent.local/runs/${runId}`));
  const detail = await response.json();

  expect(detail.operational_maturity).toMatchObject({
    schema: "waygent.operational_maturity.v1",
    run_id: runId
  });
  expect(detail.dogfood_evidence).toMatchObject({
    schema: "waygent.dogfood_evidence.v1",
    run_id: runId
  });
  expect(detail.runtime_cost).toMatchObject({
    schema: "waygent.runtime_cost.v1",
    run_id: runId
  });
  expect(detail.provider_readiness).toMatchObject({
    schema: "waygent.provider_readiness.v1",
    run_id: runId
  });
  expect(detail.apply_readiness.status).toBe("ready");
});
```

- [ ] **Step 2: Run API test to verify failure**

Run:

```bash
bun test apps/api/tests/api.test.ts
```

Expected: FAIL because real run detail lacks `operational_maturity`, `dogfood_evidence`, `runtime_cost`, and `provider_readiness`.

- [ ] **Step 3: Compute maturity projections in API detail**

In `apps/api/src/server.ts`, update imports:

```ts
import {
  projectApplyReadinessFromState,
  projectApplyState,
  projectDogfoodEvidenceFromState,
  projectExecutionExplanationFromState,
  projectFailureSummary,
  projectOperationalMaturityFromState,
  projectProviderReadinessFromState,
  projectRuntimeCostFromState,
  projectTimeline,
  projectTrustReport
} from "@waygent/lens-projectors";
```

Extend the `readRealRunDetail` return type with:

```ts
  dogfood_evidence: ReturnType<typeof projectDogfoodEvidenceFromState> | null;
  runtime_cost: ReturnType<typeof projectRuntimeCostFromState> | null;
  provider_readiness: ReturnType<typeof projectProviderReadinessFromState> | null;
  operational_maturity: ReturnType<typeof projectOperationalMaturityFromState> | null;
```

Inside `readRealRunDetail`, before `return`, add:

```ts
  const executionExplanation = stateV2 ? projectExecutionExplanationFromState(stateV2) : null;
  const failures = projectFailureSummary(events);
  const explainSummary = stateV2 && executionExplanation
    ? apiExplainSummary(stateV2, failures[0] ?? null, executionExplanation)
    : null;
  const dogfoodEvidence = stateV2
    ? projectDogfoodEvidenceFromState({ state: stateV2, events, explain_summary: explainSummary })
    : null;
  const runtimeCost = stateV2 ? projectRuntimeCostFromState(stateV2, dogfoodEvidence ?? undefined) : null;
  const providerReadiness = stateV2 ? projectProviderReadinessFromState(stateV2) : null;
  const operationalMaturity = stateV2
    ? projectOperationalMaturityFromState({ state: stateV2, events, explain_summary: explainSummary })
    : null;
```

Then in the returned object replace existing `failures` and `execution_explanation` fields and add the new fields:

```ts
    execution_explanation: executionExplanation,
    dogfood_evidence: dogfoodEvidence,
    runtime_cost: runtimeCost,
    provider_readiness: providerReadiness,
    operational_maturity: operationalMaturity,
    failures,
```

Add helper below `readRealRunDetail`:

```ts
function apiExplainSummary(
  state: WaygentRunStateV2,
  failure: ReturnType<typeof projectFailureSummary>[number] | null,
  explanation: ReturnType<typeof projectExecutionExplanationFromState>
): string {
  const blockedTask = Object.values(state.tasks).find((task) =>
    (task.status === "blocked" || task.status === "failed" || state.status === "blocked") &&
    typeof task.latest_failure_class === "string" &&
    task.latest_failure_class.length > 0
  );
  const activeFailure = blockedTask?.latest_failure_class
    ? { task_id: blockedTask.id, failure_class: blockedTask.latest_failure_class }
    : failure;
  const barrier = explanation.barriers[0];
  const hotspot = explanation.cost_hotspots[0];
  return [
    activeFailure ? `${activeFailure.task_id} blocked by ${activeFailure.failure_class}` : "no active failure barrier",
    barrier ? `scheduling barrier: ${barrier.task_id} ${barrier.reason}` : null,
    hotspot ? `cost hotspot: ${hotspot.phase} ${hotspot.duration_ms}ms` : null
  ].filter(Boolean).join("; ");
}
```

- [ ] **Step 4: Run API tests**

Run:

```bash
bun test apps/api/tests/api.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit API wiring**

Run:

```bash
git add apps/api/src/server.ts apps/api/tests/api.test.ts
git commit -m "feat: return Waygent maturity from API"
```

```yaml
id: task_console_maturity
title: Render operational maturity in the Waygent console
owner_boundary: apps/console
files:
  - path: apps/console/src/uiModel.ts
    mode: edit
  - path: apps/console/src/uiModel.test.ts
    mode: edit
  - path: apps/console/src/App.tsx
    mode: edit
  - path: apps/console/src/styles.css
    mode: edit
acceptance:
  - command: bun test apps/console/src && bun run --cwd apps/console build
  - expected: PASS
risks:
  - Console could imply diagnostic projections unlock apply. Keep apply button tied only to apply_readiness.
```

### Task 4: Render Operational Maturity In Console

**Files:**
- Modify: `apps/console/src/uiModel.ts`
- Modify: `apps/console/src/uiModel.test.ts`
- Modify: `apps/console/src/App.tsx`
- Modify: `apps/console/src/styles.css`

- [ ] **Step 1: Add failing UI model test**

In `apps/console/src/uiModel.test.ts`, add:

```ts
test("builds operational maturity section without changing apply readiness", () => {
  const model = buildRunDetailModel({
    run_id: "run_maturity",
    status: "completed",
    trust_status: "trusted",
    apply_status: "ready",
    total_events: 9,
    last_event_type: "lens.trust_report_updated",
    safe_wave: ["task_maturity"],
    failures: [],
    timeline: [],
    apply_readiness: {
      status: "ready",
      reason: null,
      checkpoint_refs: ["artifacts/checkpoints/task_maturity/candidate_task_maturity.json"],
      combined_patch_ref: "artifacts/checkpoints/apply/run_maturity.patch",
      source: "run_state_v2"
    },
    operational_maturity: {
      schema: "waygent.operational_maturity.v1",
      run_id: "run_maturity",
      status: "attention",
      top_issue: "dogfood evidence is partial",
      next_action: "Run the dogfood evidence gate and inspect missing evidence.",
      dogfood_evidence: {
        schema: "waygent.dogfood_evidence.v1",
        run_id: "run_maturity",
        status: "partial",
        checks: [],
        evidence_refs: [],
        missing_reasons: ["artifact_index missing"],
        dogfood_run_ref: null
      },
      runtime_cost: {
        schema: "waygent.runtime_cost.v1",
        run_id: "run_maturity",
        estimated_waves: 1,
        measured_waves: 1,
        parallelism_score: 1,
        serial_barriers: [],
        measured: { tasks: [{ task_id: "task_maturity", phase: "verification", duration_ms: 900 }], waves: [] },
        hotspots: [{ scope: "task", phase: "verification", duration_ms: 900, task_id: "task_maturity", wave_id: null }],
        recommended_next_actions: ["Inspect verification commands and dependency setup before increasing provider concurrency."],
        dogfood: { status: "partial", evidence_refs: [] }
      },
      provider_readiness: {
        schema: "waygent.provider_readiness.v1",
        run_id: "run_maturity",
        provider: "fake",
        status: "ready",
        command: ["fake-provider"],
        failure_class: null,
        timed_out: false,
        exit_code: 0,
        stderr_summary: null,
        recommended_next_action: "Use fake provider for deterministic local verification."
      }
    }
  });

  expect(model.sections.map((section) => section.id)).toContain("operational-maturity");
  expect(model.operational_maturity?.top_issue).toBe("dogfood evidence is partial");
  expect(model.next_action).toBe("Run the dogfood evidence gate and inspect missing evidence.");
  expect(realRunDetailToConsoleRun({
    run_id: "run_maturity",
    status: "completed",
    trust_status: "trusted",
    apply_status: "ready",
    total_events: 9,
    last_event_type: "lens.trust_report_updated",
    safe_wave: ["task_maturity"],
    failures: [],
    timeline: [],
    apply_readiness: {
      status: "ready",
      reason: null,
      checkpoint_refs: ["artifacts/checkpoints/task_maturity/candidate_task_maturity.json"],
      combined_patch_ref: "artifacts/checkpoints/apply/run_maturity.patch",
      source: "run_state_v2"
    },
    operational_maturity: model.operational_maturity
  }).applyStatus).toMatchObject({
    state: "ready",
    canApply: true
  });
});
```

- [ ] **Step 2: Run UI model test to verify failure**

Run:

```bash
bun test apps/console/src/uiModel.test.ts
```

Expected: FAIL because `RealRunDetailResponse` and `RunDetailModel` do not include `operational_maturity`.

- [ ] **Step 3: Extend console model types**

In `apps/console/src/uiModel.ts`, update imports:

```ts
import type {
  DogfoodEvidenceProjection,
  ExecutionExplanationProjection,
  OperationalMaturityProjection,
  ProviderLogSummary,
  ProviderReadinessProjection,
  RuntimeCostProjection
} from "@waygent/contracts";
```

Add `"operational-maturity"` to `RunDetailSectionId` after `"execution-intelligence"`.

Add to `RealRunDetailResponse`:

```ts
  dogfood_evidence?: DogfoodEvidenceProjection | null;
  runtime_cost?: RuntimeCostProjection | null;
  provider_readiness?: ProviderReadinessProjection | null;
  operational_maturity?: OperationalMaturityProjection | null;
```

Add to `RunDetailModel`:

```ts
  dogfood_evidence: DogfoodEvidenceProjection | null;
  runtime_cost: RuntimeCostProjection | null;
  provider_readiness: ProviderReadinessProjection | null;
  operational_maturity: OperationalMaturityProjection | null;
```

Update `buildRunDetailModel` fields:

```ts
    dogfood_evidence: response.dogfood_evidence ?? response.operational_maturity?.dogfood_evidence ?? null,
    runtime_cost: response.runtime_cost ?? response.operational_maturity?.runtime_cost ?? null,
    provider_readiness: response.provider_readiness ?? response.operational_maturity?.provider_readiness ?? null,
    operational_maturity: response.operational_maturity ?? null,
    next_action: response.operational_maturity?.next_action ?? response.execution_explanation?.recommended_next_actions[0] ?? null,
```

Add section after execution intelligence:

```ts
      { id: "operational-maturity", label: "Operational maturity" },
```

- [ ] **Step 4: Render operational maturity in App**

In `apps/console/src/App.tsx`, add this component after `ExecutionIntelligence`:

```tsx
function OperationalMaturity({ detail }: { detail: RunDetailModel }) {
  const maturity = detail.operational_maturity;
  if (!maturity) {
    return (
      <section className="section-band operational-maturity" aria-label="Operational maturity">
        <h2>Operational Maturity</h2>
        <p className="empty-state">No operational maturity projection</p>
      </section>
    );
  }

  return (
    <section className="section-band operational-maturity" aria-label="Operational maturity">
      <h2>Operational Maturity</h2>
      <div className="maturity-grid">
        <div>
          <span>Status</span>
          <strong>{maturity.status}</strong>
        </div>
        <div>
          <span>Dogfood</span>
          <strong>{maturity.dogfood_evidence.status}</strong>
        </div>
        <div>
          <span>Provider</span>
          <strong>{maturity.provider_readiness.status}</strong>
        </div>
        <div>
          <span>Runtime hotspot</span>
          <strong>{maturity.runtime_cost.hotspots[0]?.phase ?? "none"}</strong>
        </div>
      </div>
      {maturity.top_issue ? <p className="summary-line">{maturity.top_issue}</p> : null}
      <p className="next-action">Next action: {maturity.next_action}</p>
    </section>
  );
}
```

Render it after `<ExecutionIntelligence detail={detail} />`:

```tsx
          <ExecutionIntelligence detail={detail} />
          <OperationalMaturity detail={detail} />
          <OperationalEvidence detail={detail} />
```

In `apps/console/src/styles.css`, add:

```css
.operational-maturity {
  gap: 12px;
}

.maturity-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.maturity-grid > div {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  min-width: 0;
}

.maturity-grid span {
  display: block;
  color: var(--muted);
  font-size: 12px;
}

.maturity-grid strong {
  display: block;
  margin-top: 4px;
  overflow-wrap: anywhere;
}
```

- [ ] **Step 5: Run console tests and build**

Run:

```bash
bun test apps/console/src
bun run --cwd apps/console build
```

Expected: PASS.

- [ ] **Step 6: Commit console maturity surface**

Run:

```bash
git add apps/console/src/uiModel.ts apps/console/src/uiModel.test.ts apps/console/src/App.tsx apps/console/src/styles.css
git commit -m "feat: show Waygent operational maturity"
```

```yaml
id: task_dogfood_gate
title: Add deterministic dogfood evidence gate
owner_boundary: packages/testkit and tests/integration
files:
  - path: packages/testkit/src/waygentDogfood.ts
    mode: owned
  - path: packages/testkit/src/index.ts
    mode: edit
  - path: tests/integration/waygent-dogfood-evidence.test.ts
    mode: owned
  - path: package.json
    mode: edit
acceptance:
  - command: bun run waygent:dogfood
  - expected: PASS
risks:
  - Dogfood gate can become flaky if it depends on live providers. Keep it fake-provider by default and only inspect durable local evidence.
```

### Task 5: Add Deterministic Dogfood Evidence Gate

**Files:**
- Create: `packages/testkit/src/waygentDogfood.ts`
- Modify: `packages/testkit/src/index.ts`
- Create: `tests/integration/waygent-dogfood-evidence.test.ts`
- Modify: `package.json`

- [ ] **Step 1: Write failing dogfood integration test**

Create `tests/integration/waygent-dogfood-evidence.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { runWaygentDogfoodCheck } from "../../packages/testkit/src";

describe("Waygent dogfood evidence gate", () => {
  test("fake-provider dogfood run records inspectable maturity evidence", async () => {
    const result = await runWaygentDogfoodCheck();

    expect(result.run_id).toStartWith("dogfood_");
    expect(result.inspect.operational_maturity).toMatchObject({
      schema: "waygent.operational_maturity.v1"
    });
    expect(result.inspect.dogfood_evidence?.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "artifact_index" }),
        expect.objectContaining({ id: "phase_timings" }),
        expect.objectContaining({ id: "explain_summary" })
      ])
    );
    expect(result.explain.summary).toContain("no active failure barrier");
    expect(result.failures).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
bun test tests/integration/waygent-dogfood-evidence.test.ts
```

Expected: FAIL because `runWaygentDogfoodCheck` does not exist.

- [ ] **Step 3: Implement dogfood helper**

Create `packages/testkit/src/waygentDogfood.ts`:

```ts
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { explainRun, inspectRun, runWaygentDemo } from "@waygent/orchestrator";

export interface WaygentDogfoodCheckResult {
  run_id: string;
  root: string;
  workspace: string;
  inspect: ReturnType<typeof inspectRun>;
  explain: ReturnType<typeof explainRun>;
  failures: string[];
}

export async function runWaygentDogfoodCheck(): Promise<WaygentDogfoodCheckResult> {
  const root = mkdtempSync(join(tmpdir(), "waygent-dogfood-runs-"));
  const workspace = initDogfoodSourceCheckout("waygent-dogfood-source-");
  const runId = `dogfood_${Date.now()}`;
  await runWaygentDemo({ root, workspace, run_id: runId });
  const inspect = inspectRun({ root, run: runId });
  const explain = explainRun({ root, run: runId });
  const failures = dogfoodFailures(inspect, explain.summary);
  return { run_id: runId, root, workspace, inspect, explain, failures };
}

function dogfoodFailures(inspect: ReturnType<typeof inspectRun>, explainSummary: string): string[] {
  const failures: string[] = [];
  if (!inspect.operational_maturity) failures.push("missing_operational_maturity");
  if (!inspect.dogfood_evidence) failures.push("missing_dogfood_evidence");
  if (!inspect.runtime_cost) failures.push("missing_runtime_cost");
  if (!inspect.provider_readiness) failures.push("missing_provider_readiness");
  if ((inspect.state?.artifact_index ?? []).length === 0) failures.push("empty_artifact_index");
  const phaseTimingCount = Object.values(inspect.state?.tasks ?? {}).flatMap((task) => task.phase_timings ?? []).length;
  if (phaseTimingCount === 0) failures.push("missing_phase_timings");
  if (!explainSummary.includes("blocked by") && !explainSummary.includes("no active failure barrier")) {
    failures.push("imprecise_explain_summary");
  }
  return failures;
}

function initDogfoodSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  writeFileSync(join(workspace, "README.md"), "dogfood fixture\n");
  for (const args of [
    ["init", "-q"],
    ["config", "user.email", "test@example.com"],
    ["config", "user.name", "Waygent"],
    ["add", "-A"],
    ["commit", "-q", "-m", "init"]
  ]) {
    const result = Bun.spawnSync(["git", ...args], { cwd: workspace });
    if (result.exitCode !== 0) throw new Error(`git ${args.join(" ")} failed`);
  }
  return workspace;
}
```

Modify `packages/testkit/src/index.ts`:

```ts
export * from "./legacyCheck";
export * from "./waygentScenarioHarness";
export * from "./waygentDogfood";
```

Modify `package.json` scripts:

```json
"waygent:dogfood": "bun test tests/integration/waygent-dogfood-evidence.test.ts"
```

- [ ] **Step 4: Run dogfood gate**

Run:

```bash
bun run waygent:dogfood
```

Expected: PASS.

- [ ] **Step 5: Commit dogfood gate**

Run:

```bash
git add packages/testkit/src/waygentDogfood.ts packages/testkit/src/index.ts tests/integration/waygent-dogfood-evidence.test.ts package.json
git commit -m "test: add Waygent dogfood maturity gate"
```

```yaml
id: task_docs_final_gate
title: Document the maturity loop and refresh repo map
owner_boundary: docs and final verification
files:
  - path: docs/operations/waygent.md
    mode: edit
  - path: docs/operations/verification.md
    mode: edit
  - path: docs/architecture/waygent.md
    mode: edit
  - path: graphify-out/GRAPH_REPORT.md
    mode: edit
  - path: graphify-out/graph.json
    mode: edit
acceptance:
  - command: bun run check && bun run platform:demo && bun run waygent:scenarios && bun run waygent:dogfood && bun run check:legacy && bun run --cwd apps/console build && git diff --check
  - expected: PASS
risks:
  - Documentation can imply dogfood evidence controls apply. State that maturity projections are read-only diagnostics.
```

### Task 6: Document The Loop And Run Final Verification

**Files:**
- Modify: `docs/operations/waygent.md`
- Modify: `docs/operations/verification.md`
- Modify: `docs/architecture/waygent.md`
- Modify: `graphify-out/GRAPH_REPORT.md`
- Modify: `graphify-out/graph.json`

- [ ] **Step 1: Update operations docs**

In `docs/operations/waygent.md`, under `## Execution Intelligence`, add:

```md
## Operational Maturity Loop

Waygent exposes dogfood evidence, runtime cost, and provider readiness as
read-only diagnostics through `inspect`, API, and console.

Use the loop in this order:

1. Run or resume through Waygent.
2. Inspect durable evidence with `waygent inspect --run <run_id> --json`.
3. Read the shortest diagnosis with `waygent explain --run <run_id>`.
4. Repair the provider, verification environment, plan structure, or missing
   artifacts named by the projection.
5. Rerun or resume only through Waygent.

The maturity projection does not authorize apply. Apply readiness still comes
from completion audit, checkpoint manifests, combined patch evidence,
reconciliation, and clean source checkout validation.
```

- [ ] **Step 2: Update verification docs**

In `docs/operations/verification.md`, after `Default Offline Gate`, add:

````md
## Dogfood Evidence Gate

```bash
bun run waygent:dogfood
```

This gate runs a deterministic fake-provider Waygent execution and verifies
that `inspect` and `explain` expose operational maturity evidence. It checks
for artifact index records, task phase timings, provider attempts,
verification evidence, runtime timestamps, provider readiness, runtime cost,
and a precise explain summary. It does not use live providers.
````

Use a nested fenced block carefully: the outer plan block is closed above, so
the markdown added to `verification.md` must use the exact text shown.

- [ ] **Step 3: Update architecture docs**

In `docs/architecture/waygent.md`, after the `V1 Operational Maturity` list, add:

```md
## Operational Maturity Loop

The operational maturity loop is the read-only diagnostic layer over
`waygent.run_state.v2`. It combines dogfood evidence, runtime cost, provider
readiness, execution explanation, and apply readiness into one operator view.

The loop answers why a run is blocked, why it was slow or serial, whether the
diagnostic evidence is complete, and what the next safe action is. It is not a
mutation path and cannot mark a run apply-ready.
```

- [ ] **Step 4: Run targeted and full verification**

Run:

```bash
bun test packages/lens-projectors/tests/operationalMaturity.test.ts \
  packages/orchestrator/tests/runCommandsV2.test.ts \
  apps/api/tests/api.test.ts \
  apps/console/src/uiModel.test.ts \
  tests/integration/waygent-dogfood-evidence.test.ts
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:dogfood
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

Expected: PASS.

- [ ] **Step 5: Refresh Graphify**

Run:

```bash
graphify update .
```

Expected: `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.json` are updated or Graphify reports no topology changes.

- [ ] **Step 6: Commit docs and final graph**

Run:

```bash
git add docs/operations/waygent.md docs/operations/verification.md docs/architecture/waygent.md graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "docs: document Waygent maturity loop"
```

## Execution Order

Sequential tasks:

1. `task_projection_contracts`
2. `task_cli_maturity`
3. `task_api_maturity`
4. `task_console_maturity`
5. `task_dogfood_gate`
6. `task_docs_final_gate`

Parallel notes:

- Task 3 and Task 4 both depend on Task 1. They should not run concurrently in the same worktree because both can touch response shapes consumed by the console.
- Task 5 depends on Task 2 because the dogfood helper asserts `inspectRun` and `explainRun` maturity fields.
- Task 6 runs last because it documents final command behavior and refreshes Graphify.

Human approval gates:

- Review after Task 1 if projection names or status values differ from the spec.
- Review after Task 4 if console layout becomes visually noisy.
- Review before running live provider smoke. Live provider checks are not part of this plan's default gate.

## Final Verification

Run:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:dogfood
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

Optional live provider verification:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Do not report optional live smoke as failed if the provider CLI is not installed or authenticated. Report it as skipped by environment.

## Review Checklist

- `inspect --json` exposes `dogfood_evidence`, `runtime_cost`, `provider_readiness`, and `operational_maturity`.
- `explain` prioritizes hard blockers before runtime hotspots and dogfood evidence gaps.
- API real run detail returns the same projection shapes as CLI inspect.
- Console renders operational maturity as read-only evidence.
- Apply button state still comes only from `apply_readiness`.
- Dogfood gate uses fake provider by default and does not require live provider auth.
- Default verification passes.
- `graphify update .` has been run after code and docs changes.
