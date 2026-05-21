# Waygent Execution Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable Waygent execution explanations, fixed-cost timing, worktree management, and artifact-index-backed reconciliation without weakening apply readiness.

**Architecture:** Keep `waygent.run_state.v2` as the runtime source of truth. Add shared contract types, a `packages/lens-projectors` execution explanation projector, then wire `inspect`, API, and console to the same model. After the read-only explanation surface works, centralize task worktree setup and artifact indexing inside `packages/orchestrator`.

**Tech Stack:** TypeScript, Bun test runner, `@waygent/contracts`, `@waygent/lens-projectors`, `@waygent/orchestrator`, `apps/api`, `apps/console`, filesystem JSON artifacts.

---

## Context

Relevant design:

- `docs/superpowers/specs/2026-05-22-waygent-execution-intelligence-design.md`

Relevant runtime files:

- `packages/contracts/src/types.ts`
- `packages/contracts/src/schemas.ts`
- `packages/lens-projectors/src/index.ts`
- `packages/orchestrator/src/runCommands.ts`
- `packages/orchestrator/src/orchestrator.ts`
- `packages/orchestrator/src/taskExecutor.ts`
- `packages/orchestrator/src/checkpointArtifacts.ts`
- `packages/orchestrator/src/stateReconciliation.ts`
- `apps/api/src/server.ts`
- `apps/console/src/uiModel.ts`
- `apps/console/src/App.tsx`

Constraints:

- Do not reintroduce AgentRunway or KWS executor skills as active routing.
- Do not let an explanation projection authorize apply readiness.
- Do not bypass checkpoint manifests, patch digest checks, dry-run evidence,
  completion audit, reconciliation, or clean-checkout apply rules.
- Keep live provider smoke checks opt-in.

## File Structure

- `packages/contracts/src/types.ts`: owns shared TypeScript shapes for phase timing, artifact index entries, artifact health, barriers, hotspots, and the execution explanation projection.
- `packages/contracts/src/schemas.ts`: accepts optional execution-intelligence fields in `waygent.run_state.v2` and extends worktree cleanup status to include `failed`.
- `packages/lens-projectors/src/executionExplanation.ts`: pure projection from `WaygentRunStateV2` to `ExecutionExplanationProjection`.
- `packages/lens-projectors/tests/executionExplanation.test.ts`: unit coverage for barriers, cost hotspots, artifact health, and recommendations.
- `packages/orchestrator/src/worktreeManager.ts`: owns task worktree preparation and setup timing.
- `packages/orchestrator/tests/worktreeManager.test.ts`: targeted worktree setup tests.
- `packages/orchestrator/src/artifactIndex.ts`: creates and validates run-local artifact index entries.
- `packages/orchestrator/tests/artifactIndex.test.ts`: targeted artifact-index tests.
- `packages/orchestrator/src/taskExecutor.ts`: returns phase timing and artifact index entries from task-local execution.
- `packages/orchestrator/src/orchestrator.ts`: records phase timing, artifact index entries, worktree manifests, and combined apply evidence entries into run state.
- `packages/orchestrator/src/stateReconciliation.ts`: uses artifact index lookup before byte-level validation.
- `packages/orchestrator/src/runCommands.ts`: includes execution explanation in inspect and explain results.
- `apps/api/src/server.ts`: includes execution explanation in real run detail responses.
- `apps/console/src/uiModel.ts`: carries execution explanation into the UI model.
- `apps/console/src/App.tsx`: renders execution intelligence as operator evidence.

## Execution Order

Sequential core path:

1. Task 1: shared contracts.
2. Task 2: read-only projector.
3. Task 3: inspect/API exposure.
4. Task 4: console exposure.
5. Task 5: WorktreeManager and phase timing.
6. Task 6: ArtifactIndex.
7. Task 7: index-assisted reconciliation.
8. Task 8: docs and full verification.

Parallel-safe after Task 2:

- Task 3 and Task 4 can be implemented by separate workers if their write
  scopes stay disjoint: Task 3 owns CLI/API, Task 4 owns console.

Shared-core tasks that should remain sequential:

- Task 5, Task 6, and Task 7 all touch orchestrator state mutation and
  reconciliation. Run them in order.

## Task 1: Add Execution Intelligence Contracts

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/contracts/tests/contracts.test.ts`

- [ ] **Step 1: Write failing contract test edits**

In the existing `accepts additive Waygent v2 state preflight, worktree, and provider process evidence` test in `packages/contracts/tests/contracts.test.ts`, change the worktree cleanup status:

```ts
          cleanup_status: "failed"
```

Add `phase_timings` to the existing `task_demo` object in that same test:

```ts
          phase_timings: [
            {
              phase: "provider",
              started: "2026-05-22T00:00:00.000Z",
              completed: "2026-05-22T00:00:01.000Z",
              duration_ms: 1000
            }
          ]
```

Add `artifact_index` before `tasks` in that same state object:

```ts
      artifact_index: [
        {
          ref: "artifacts/worker/task_demo.json",
          media_type: "application/json",
          sha256: "a".repeat(64),
          byte_length: 42,
          producer_phase: "provider",
          task_id: "task_demo",
          created_at: "2026-05-22T00:00:00.000Z"
        }
      ],
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
```

Expected: FAIL because `artifact_index`, `phase_timings`, or `cleanup_status: "failed"` is rejected by the schema.

- [ ] **Step 3: Add shared types**

In `packages/contracts/src/types.ts`, add these types near the Waygent run-state types:

```ts
export type ExecutionPhaseName =
  | "worktree_setup"
  | "provider"
  | "verification"
  | "checkpoint"
  | "checkpoint_dry_run"
  | "reconciliation"
  | "wave"
  | "total";

export interface ExecutionPhaseTiming {
  phase: ExecutionPhaseName;
  started: string | null;
  completed: string | null;
  duration_ms: number | null;
}

export interface ArtifactIndexEntry {
  ref: string;
  media_type: string;
  sha256: string;
  byte_length: number;
  producer_phase: ExecutionPhaseName | "task_packet" | "combined_apply" | "decision";
  task_id: string | null;
  created_at: string;
}

export interface ExecutionBarrier {
  task_id: string;
  reason: string;
  detail: string;
  wave_id: string | null;
  category: "dependency" | "checkpoint" | "file_claim" | "risk" | "failure" | "source" | "unknown";
}

export interface ExecutionCostHotspot {
  scope: "run" | "wave" | "task";
  phase: ExecutionPhaseName;
  duration_ms: number;
  task_id: string | null;
  wave_id: string | null;
}

export interface ArtifactHealthSummary {
  indexed_count: number;
  missing_count: number;
  drift_count: number;
  readiness_artifact_refs: string[];
}

export interface ExecutionExplanationProjection {
  schema: "waygent.execution_explanation.v1";
  run_id: string;
  status_summary: string;
  waves: Array<{
    wave_id: string;
    ready: string[];
    concurrency: number | null;
    duration_ms: number | null;
    withheld: Array<{ task_id: string; reason: string; detail: string | null }>;
  }>;
  barriers: ExecutionBarrier[];
  cost_hotspots: ExecutionCostHotspot[];
  artifact_health: ArtifactHealthSummary;
  recommended_next_actions: string[];
}
```

Update `WaygentWorktreeManifest` and `WaygentRunStateTaskV2`:

```ts
export interface WaygentWorktreeManifest {
  task_id: string;
  branch: string;
  path: string;
  source: string;
  source_commit: string | null;
  cleanup_status: "active" | "removed" | "failed" | "unknown";
}
```

```ts
export interface WaygentRunStateTaskV2 {
  id: string;
  status: WaygentTaskStatusV2;
  risk: RiskLevel;
  dependencies: string[];
  file_claims: WaygentFileClaim[];
  attempts: string[];
  task_packet_path: string | null;
  task_packet_sha256: string | null;
  unit_manifest: Record<string, unknown> | null;
  checkpoint_refs: string[];
  latest_failure_class: FailureClass | string | null;
  decision_packet_ref: string | null;
  timing: Record<string, string>;
  phase_timings?: ExecutionPhaseTiming[];
}
```

Update `WaygentRunStateV2`:

```ts
export interface WaygentRunStateV2 {
  schema: "waygent.run_state.v2";
  run_id: string;
  workspace: string;
  source_branch: string | null;
  worktree_root: string;
  run_root: string;
  artifact_root: string;
  state_path: string;
  event_journal_path: string;
  plan_path: string | null;
  spec_path: string | null;
  provider_profile: Record<string, unknown>;
  status: WaygentRunStatusV2;
  lifecycle_outcome: WaygentLifecycleOutcome;
  current_phase: WaygentCurrentPhase;
  preflight?: WaygentSourcePreflight;
  worktrees?: WaygentWorktreeManifest[];
  artifact_index?: ArtifactIndexEntry[];
  tasks: Record<string, WaygentRunStateTaskV2>;
  safe_waves: Array<{
    wave_id: string;
    ready: string[];
    withheld: Array<{ task_id: string; reason: string; detail?: string }>;
    concurrency?: number;
    timing?: { started: string; completed: string; duration_ms: number };
  }>;
  provider_attempts: ProviderAttempt[];
  reviews: ReviewResult[];
  verification: Array<Record<string, unknown>>;
  recovery: Array<Record<string, unknown>>;
  apply: { status: "not_applied" | "not_ready" | "blocked" | "applying" | "applied" | "failed"; reason?: string; checkpoint_ref?: string };
  context: { snapshot_path: string | null; basis_hash: string | null };
  drift: { last_checked_at: string | null; records: Array<Record<string, unknown>>; unrepaired_blockers: Array<Record<string, unknown>> };
  completion_audit: null | Record<string, unknown>;
  timestamps: { started_at: string; updated_at: string; completed_at: string | null };
}
```

- [ ] **Step 4: Update schemas**

In `packages/contracts/src/schemas.ts`, add schemas matching the new types:

```ts
const executionPhaseNameValues = [
  "worktree_setup",
  "provider",
  "verification",
  "checkpoint",
  "checkpoint_dry_run",
  "reconciliation",
  "wave",
  "total"
] as const;

const executionPhaseTimingSchema = {
  type: "object",
  additionalProperties: false,
  required: ["phase", "started", "completed", "duration_ms"],
  properties: {
    phase: { enum: executionPhaseNameValues },
    started: { type: "string", pattern: isoTimestamp, nullable: true },
    completed: { type: "string", pattern: isoTimestamp, nullable: true },
    duration_ms: { type: "number", minimum: 0, nullable: true }
  }
} as const;

const artifactIndexEntrySchema = {
  type: "object",
  additionalProperties: false,
  required: ["ref", "media_type", "sha256", "byte_length", "producer_phase", "task_id", "created_at"],
  properties: {
    ref: { type: "string", minLength: 1 },
    media_type: { type: "string", minLength: 1 },
    sha256: { type: "string", pattern: "^[a-f0-9]{64}$" },
    byte_length: { type: "number", minimum: 0 },
    producer_phase: { enum: [...executionPhaseNameValues, "task_packet", "combined_apply", "decision"] },
    task_id: { type: "string", pattern: idPattern, nullable: true },
    created_at: { type: "string", pattern: isoTimestamp }
  }
} as const;
```

Update `waygentWorktreeManifestSchema.cleanup_status`:

```ts
cleanup_status: { enum: ["active", "removed", "failed", "unknown"] }
```

Add `phase_timings` to `waygentRunStateTaskV2Schema.properties`:

```ts
phase_timings: { type: "array", items: executionPhaseTimingSchema }
```

Add `artifact_index` to `waygentRunStateV2Schema.properties`:

```ts
artifact_index: { type: "array", items: artifactIndexEntrySchema }
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/contracts/tests/contracts.test.ts
git commit -m "feat: add Waygent execution intelligence contracts"
```

## Task 2: Add Execution Explanation Projector

**Files:**
- Create: `packages/lens-projectors/src/executionExplanation.ts`
- Modify: `packages/lens-projectors/src/index.ts`
- Create: `packages/lens-projectors/tests/executionExplanation.test.ts`

- [ ] **Step 1: Write projector tests**

Create `packages/lens-projectors/tests/executionExplanation.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { projectExecutionExplanationFromState } from "../src";

describe("execution explanation projector", () => {
  test("explains waves, barriers, hotspots, and artifact health", () => {
    const projection = projectExecutionExplanationFromState(makeState({
      safe_waves: [
        {
          wave_id: "wave_1",
          ready: ["task_a"],
          concurrency: 1,
          timing: {
            started: "2026-05-22T00:00:00.000Z",
            completed: "2026-05-22T00:00:03.000Z",
            duration_ms: 3000
          },
          withheld: [{ task_id: "task_b", reason: "file_claim_conflict", detail: "README.md is already claimed" }]
        }
      ],
      artifact_index: [
        {
          ref: "artifacts/checkpoints/task_a/candidate_task_a.json",
          media_type: "application/json",
          sha256: "a".repeat(64),
          byte_length: 12,
          producer_phase: "checkpoint",
          task_id: "task_a",
          created_at: "2026-05-22T00:00:01.000Z"
        }
      ],
      tasks: {
        task_a: task("task_a", {
          phase_timings: [
            { phase: "provider", started: "2026-05-22T00:00:00.000Z", completed: "2026-05-22T00:00:02.000Z", duration_ms: 2000 }
          ]
        }),
        task_b: task("task_b", { status: "ready", checkpoint_refs: [] })
      },
      completion_audit: {
        status: "passed",
        combined_apply_evidence: {
          status: "passed",
          checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
          patch_ref: "artifacts/checkpoints/apply/run_demo.patch"
        }
      }
    }));

    expect(projection).toMatchObject({
      schema: "waygent.execution_explanation.v1",
      run_id: "run_demo",
      waves: [
        {
          wave_id: "wave_1",
          ready: ["task_a"],
          concurrency: 1,
          duration_ms: 3000,
          withheld: [{ task_id: "task_b", reason: "file_claim_conflict", detail: "README.md is already claimed" }]
        }
      ],
      barriers: [
        {
          task_id: "task_b",
          reason: "file_claim_conflict",
          category: "file_claim"
        }
      ],
      artifact_health: {
        indexed_count: 1,
        missing_count: 0,
        drift_count: 0,
        readiness_artifact_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json", "artifacts/checkpoints/apply/run_demo.patch"]
      }
    });
    expect(projection.cost_hotspots[0]).toMatchObject({ phase: "wave", duration_ms: 3000, wave_id: "wave_1" });
    expect(projection.recommended_next_actions).toContain("Split overlapping file claims or add dependencies so safe waves can stay parallel.");
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
    tasks: {},
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

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
bun test packages/lens-projectors/tests/executionExplanation.test.ts
```

Expected: FAIL because `projectExecutionExplanationFromState` is not exported.

- [ ] **Step 3: Implement the projector**

Create `packages/lens-projectors/src/executionExplanation.ts`:

```ts
import type {
  ArtifactHealthSummary,
  ExecutionBarrier,
  ExecutionCostHotspot,
  ExecutionExplanationProjection,
  ExecutionPhaseName,
  WaygentRunStateV2
} from "@waygent/contracts";

const readinessRefKeys = ["checkpoint_refs", "patch_ref", "evidence_ref"] as const;

export function projectExecutionExplanationFromState(state: WaygentRunStateV2): ExecutionExplanationProjection {
  const barriers = state.safe_waves.flatMap((wave) =>
    wave.withheld.map((item): ExecutionBarrier => ({
      task_id: item.task_id,
      reason: item.reason,
      detail: item.detail ?? item.reason,
      wave_id: wave.wave_id,
      category: barrierCategory(item.reason)
    }))
  );
  const costHotspots = costHotspotsFromState(state);
  const artifactHealth = artifactHealthFromState(state);
  return {
    schema: "waygent.execution_explanation.v1",
    run_id: state.run_id,
    status_summary: statusSummary(state, barriers, costHotspots),
    waves: state.safe_waves.map((wave) => ({
      wave_id: wave.wave_id,
      ready: wave.ready,
      concurrency: wave.concurrency ?? null,
      duration_ms: wave.timing?.duration_ms ?? null,
      withheld: wave.withheld.map((item) => ({
        task_id: item.task_id,
        reason: item.reason,
        detail: item.detail ?? null
      }))
    })),
    barriers,
    cost_hotspots: costHotspots,
    artifact_health: artifactHealth,
    recommended_next_actions: recommendations(barriers, costHotspots, artifactHealth)
  };
}

function barrierCategory(reason: string): ExecutionBarrier["category"] {
  if (reason.includes("dependency")) return "dependency";
  if (reason.includes("checkpoint")) return "checkpoint";
  if (reason.includes("claim")) return "file_claim";
  if (reason.includes("risk")) return "risk";
  if (reason.includes("failure")) return "failure";
  if (reason.includes("dirty") || reason.includes("source")) return "source";
  return "unknown";
}

function costHotspotsFromState(state: WaygentRunStateV2): ExecutionCostHotspot[] {
  const hotspots: ExecutionCostHotspot[] = [];
  for (const wave of state.safe_waves) {
    if (typeof wave.timing?.duration_ms === "number") {
      hotspots.push({ scope: "wave", phase: "wave", duration_ms: wave.timing.duration_ms, task_id: null, wave_id: wave.wave_id });
    }
  }
  for (const task of Object.values(state.tasks)) {
    for (const timing of task.phase_timings ?? []) {
      if (typeof timing.duration_ms === "number") {
        hotspots.push({ scope: "task", phase: timing.phase, duration_ms: timing.duration_ms, task_id: task.id, wave_id: null });
      }
    }
  }
  return hotspots.sort((a, b) => b.duration_ms - a.duration_ms).slice(0, 5);
}

function artifactHealthFromState(state: WaygentRunStateV2): ArtifactHealthSummary {
  const readinessRefs = readinessRefsFromCompletionAudit(state.completion_audit);
  const driftRecords = state.drift.records.filter((record) => String(record.failure_class ?? record.type ?? "").includes("drift"));
  const missingRecords = state.drift.records.filter((record) => String(record.failure_class ?? record.type ?? "").includes("missing"));
  return {
    indexed_count: state.artifact_index?.length ?? 0,
    missing_count: missingRecords.length,
    drift_count: driftRecords.length,
    readiness_artifact_refs: readinessRefs
  };
}

function readinessRefsFromCompletionAudit(audit: Record<string, unknown> | null): string[] {
  const combined = audit?.combined_apply_evidence;
  if (!combined || typeof combined !== "object") return [];
  const refs = new Set<string>();
  for (const key of readinessRefKeys) {
    const value = (combined as Record<string, unknown>)[key];
    if (typeof value === "string" && value.length > 0) refs.add(value);
    if (Array.isArray(value)) {
      for (const ref of value) {
        if (typeof ref === "string" && ref.length > 0) refs.add(ref);
      }
    }
  }
  return [...refs];
}

function statusSummary(
  state: WaygentRunStateV2,
  barriers: ExecutionBarrier[],
  hotspots: ExecutionCostHotspot[]
): string {
  if (barriers.length > 0) return `${state.run_id} has ${barriers.length} scheduling barrier${barriers.length === 1 ? "" : "s"}.`;
  const hotspot = hotspots[0];
  if (hotspot) return `${state.run_id} spent most recorded time in ${hotspot.phase}.`;
  return `${state.run_id} has no recorded scheduling barriers.`;
}

function recommendations(
  barriers: ExecutionBarrier[],
  hotspots: ExecutionCostHotspot[],
  health: ArtifactHealthSummary
): string[] {
  const result = new Set<string>();
  if (barriers.some((barrier) => barrier.category === "file_claim")) {
    result.add("Split overlapping file claims or add dependencies so safe waves can stay parallel.");
  }
  if (barriers.some((barrier) => barrier.category === "risk")) {
    result.add("Reduce high-risk task scope before expecting wider safe waves.");
  }
  if (hotspots.some((hotspot) => hotspot.phase === "worktree_setup")) {
    result.add("Inspect worktree setup cost before changing provider concurrency.");
  }
  if (health.missing_count > 0 || health.drift_count > 0) {
    result.add("Repair missing or drifted artifacts before applying checkpoints.");
  }
  if (result.size === 0) result.add("No trust-preserving optimization is recommended from the recorded evidence.");
  return [...result];
}
```

Update `packages/lens-projectors/src/index.ts`:

```ts
export * from "./trust";
export * from "./apply";
export * from "./executionExplanation";
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
bun test packages/lens-projectors/tests/executionExplanation.test.ts packages/lens-projectors/tests/apply.test.ts packages/lens-projectors/tests/trust.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add packages/lens-projectors/src/index.ts packages/lens-projectors/src/executionExplanation.ts packages/lens-projectors/tests/executionExplanation.test.ts
git commit -m "feat: project Waygent execution explanations"
```

## Task 3: Expose Explanation In Inspect And API

**Files:**
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/orchestrator/tests/runCommandsV2.test.ts`
- Modify: `apps/api/src/server.ts`
- Modify: `apps/api/tests/api.test.ts`

- [ ] **Step 1: Add focused CLI/API tests**

Append this test to `packages/orchestrator/tests/runCommandsV2.test.ts`:

```ts
// Update the existing import from "../src/runCommands" to include explainRun and inspectRun.
test("inspect and explain include execution explanation for v2 runs", () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-inspect-explanation-"));
  const runId = "run_explain_v2";
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
        ready: ["task_a"],
        concurrency: 1,
        timing: {
          started: "2026-05-22T00:00:00.000Z",
          completed: "2026-05-22T00:00:01.000Z",
          duration_ms: 1000
        },
        withheld: [{ task_id: "task_b", reason: "file_claim_conflict", detail: "same file" }]
      }
    ],
    tasks: {
      task_a: {
        id: "task_a",
        status: "verified",
        risk: "low",
        dependencies: [],
        file_claims: [{ path: "a.txt", mode: "owned" }],
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

  const inspected = inspectRun({ root, run: runId });
  expect(inspected.execution_explanation).toMatchObject({
    schema: "waygent.execution_explanation.v1",
    barriers: [{ task_id: "task_b", reason: "file_claim_conflict" }]
  });
  expect(explainRun({ root, run: runId }).summary).toContain("file_claim_conflict");
});
```

Append this test to `apps/api/tests/api.test.ts`:

```ts
test("GET /runs/:runId exposes execution explanation for real v2 runs", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-api-explanation-"));
  await runWaygentDemo({ root, run_id: "run_api_explanation" });
  const realHandler = createApiHandler({ runRoot: root });

  const response = await realHandler(new Request("http://waygent.local/runs/run_api_explanation"));
  const detail = await response.json();

  expect(detail.execution_explanation).toMatchObject({
    schema: "waygent.execution_explanation.v1",
    run_id: "run_api_explanation"
  });
  expect(Array.isArray(detail.execution_explanation.waves)).toBe(true);
  expect(Array.isArray(detail.execution_explanation.recommended_next_actions)).toBe(true);
});
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```bash
bun test packages/orchestrator/tests/runCommandsV2.test.ts apps/api/tests/api.test.ts
```

Expected: FAIL because `execution_explanation` is not returned.

- [ ] **Step 3: Wire run commands**

In `packages/orchestrator/src/runCommands.ts`, add the import:

```ts
import { projectApplyReadinessFromState, projectExecutionExplanationFromState, projectFailureSummary, projectTrustReport } from "@waygent/lens-projectors";
```

Update `inspectRun` return type to include:

```ts
execution_explanation?: ReturnType<typeof projectExecutionExplanationFromState>;
```

Update the successful state branch in `inspectRun`:

```ts
...(stateResult.status === "ok"
  ? {
    state: stateResult.state,
    execution_explanation: projectExecutionExplanationFromState(stateResult.state)
  }
  : { state_error: stateResult })
```

Update `explainRun` after reading events:

```ts
const stateResult = readRunStateV2Result(options.root, runId);
if (stateResult.status === "ok") {
  const explanation = projectExecutionExplanationFromState(stateResult.state);
  const barrier = explanation.barriers[0];
  const hotspot = explanation.cost_hotspots[0];
  const summaryParts = [
    failure ? `${failure.task_id} blocked by ${failure.failure_class}` : "no active failure barrier",
    barrier ? `scheduling barrier: ${barrier.task_id} ${barrier.reason}` : null,
    hotspot ? `cost hotspot: ${hotspot.phase} ${hotspot.duration_ms}ms` : null
  ].filter(Boolean);
  return {
    run_id: runId,
    blocked_by: failure?.failure_class ?? null,
    summary: summaryParts.join("; ")
  };
}
```

- [ ] **Step 4: Wire API detail**

In `apps/api/src/server.ts`, add the import:

```ts
projectExecutionExplanationFromState,
```

Add `execution_explanation` to the `readRealRunDetail` return type:

```ts
execution_explanation: ReturnType<typeof projectExecutionExplanationFromState> | null;
```

Add this property to the returned object:

```ts
execution_explanation: stateV2 ? projectExecutionExplanationFromState(stateV2) : null,
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
bun test packages/orchestrator/tests/runCommandsV2.test.ts apps/api/tests/api.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add packages/orchestrator/src/runCommands.ts packages/orchestrator/tests/runCommandsV2.test.ts apps/api/src/server.ts apps/api/tests/api.test.ts
git commit -m "feat: expose Waygent execution explanations"
```

## Task 4: Render Execution Intelligence In Console

**Files:**
- Modify: `apps/console/src/uiModel.ts`
- Modify: `apps/console/src/uiModel.test.ts`
- Modify: `apps/console/src/App.tsx`
- Modify: `apps/console/src/styles.css`

- [ ] **Step 1: Add UI model tests**

Append this test to `apps/console/src/uiModel.test.ts`:

```ts
test("builds execution intelligence detail from API response", () => {
  const model = buildRunDetailModel({
    run_id: "run_intel",
    status: "blocked",
    trust_status: "failed",
    apply_status: "blocked",
    total_events: 4,
    last_event_type: "runway.safe_wave_selected",
    safe_wave: ["task_a"],
    failures: [],
    timeline: [],
    execution_explanation: {
      schema: "waygent.execution_explanation.v1",
      run_id: "run_intel",
      status_summary: "run_intel has 1 scheduling barrier.",
      waves: [
        {
          wave_id: "wave_1",
          ready: ["task_a"],
          concurrency: 1,
          duration_ms: 1200,
          withheld: [{ task_id: "task_b", reason: "file_claim_conflict", detail: "README.md" }]
        }
      ],
      barriers: [
        {
          task_id: "task_b",
          reason: "file_claim_conflict",
          detail: "README.md",
          wave_id: "wave_1",
          category: "file_claim"
        }
      ],
      cost_hotspots: [
        {
          scope: "wave",
          phase: "wave",
          duration_ms: 1200,
          task_id: null,
          wave_id: "wave_1"
        }
      ],
      artifact_health: {
        indexed_count: 2,
        missing_count: 0,
        drift_count: 0,
        readiness_artifact_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"]
      },
      recommended_next_actions: ["Split overlapping file claims or add dependencies so safe waves can stay parallel."]
    }
  });

  expect(model.execution_explanation?.barriers[0]).toMatchObject({
    task_id: "task_b",
    category: "file_claim"
  });
  expect(model.sections.map((section) => section.id)).toContain("execution-intelligence");
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
bun test apps/console/src/uiModel.test.ts
```

Expected: FAIL because `execution_explanation` is not part of the response/model.

- [ ] **Step 3: Extend UI model types**

In `apps/console/src/uiModel.ts`, import the shared type:

```ts
import type { ExecutionExplanationProjection } from "@waygent/contracts";
```

Extend `RunDetailSectionId`:

```ts
  | "execution-intelligence"
```

Extend `RealRunDetailResponse`:

```ts
  execution_explanation?: ExecutionExplanationProjection | null;
```

Extend `RunDetailModel`:

```ts
  execution_explanation: ExecutionExplanationProjection | null;
```

In `buildRunDetailModel`, add:

```ts
    execution_explanation: response.execution_explanation ?? null,
```

Add the section after safe wave:

```ts
      { id: "execution-intelligence", label: "Execution intelligence" },
```

- [ ] **Step 4: Render the console section**

In `apps/console/src/App.tsx`, add this component above `OperationalEvidence`:

```tsx
function ExecutionIntelligence({ detail }: { detail: RunDetailModel }) {
  const explanation = detail.execution_explanation;
  return (
    <section className="section-band execution-intelligence" aria-label="Execution intelligence">
      <h2>Execution intelligence</h2>
      {explanation ? (
        <>
          <p className="summary-line">{explanation.status_summary}</p>
          <div className="intel-grid">
            <div>
              <span>Waves</span>
              <strong>{explanation.waves.length}</strong>
            </div>
            <div>
              <span>Barriers</span>
              <strong>{explanation.barriers.length}</strong>
            </div>
            <div>
              <span>Indexed artifacts</span>
              <strong>{explanation.artifact_health.indexed_count}</strong>
            </div>
            <div>
              <span>Artifact blockers</span>
              <strong>{explanation.artifact_health.missing_count + explanation.artifact_health.drift_count}</strong>
            </div>
          </div>
          <EvidenceList title="Cost Hotspots" items={explanation.cost_hotspots} empty="No cost hotspots" />
          <EvidenceList title="Scheduling Barriers" items={explanation.barriers} empty="No scheduling barriers" />
        </>
      ) : (
        <p className="empty-state">No execution explanation</p>
      )}
    </section>
  );
}
```

Render it before `OperationalEvidence`:

```tsx
          <ExecutionIntelligence detail={detail} />
          <OperationalEvidence detail={detail} />
```

- [ ] **Step 5: Add minimal styles**

In `apps/console/src/styles.css`, add:

```css
.execution-intelligence {
  display: grid;
  gap: 12px;
}

.summary-line {
  margin: 0;
  color: var(--muted);
  font-size: 0.95rem;
}

.intel-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.intel-grid > div {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  background: var(--surface);
}

.intel-grid span {
  display: block;
  color: var(--muted);
  font-size: 0.75rem;
}

.intel-grid strong {
  display: block;
  margin-top: 4px;
}
```

- [ ] **Step 6: Run focused tests and build**

Run:

```bash
bun test apps/console/src/uiModel.test.ts
bun run --cwd apps/console build
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add apps/console/src/uiModel.ts apps/console/src/uiModel.test.ts apps/console/src/App.tsx apps/console/src/styles.css
git commit -m "feat: show Waygent execution intelligence in console"
```

## Task 5: Centralize Worktree Setup And Phase Timing

**Files:**
- Create: `packages/orchestrator/src/worktreeManager.ts`
- Create: `packages/orchestrator/tests/worktreeManager.test.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/tests/taskExecutor.test.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/tests/orchestratorParallel.test.ts`

- [ ] **Step 1: Write WorktreeManager test**

Create `packages/orchestrator/tests/worktreeManager.test.ts`:

```ts
import { existsSync } from "node:fs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { prepareManagedTaskWorktree } from "../src/worktreeManager";
import { initSourceCheckout } from "./support/orchestratorFixtures";

describe("WorktreeManager", () => {
  test("prepares an isolated task worktree and records setup timing", () => {
    const workspace = initSourceCheckout("waygent-worktree-manager-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-worktree-manager-root-"));

    const result = prepareManagedTaskWorktree({
      run_id: "run_worktree",
      task_id: "task_a",
      workspace,
      worktree_root: join(root, "worktrees")
    });

    expect(existsSync(result.manifest.path)).toBe(true);
    expect(result.manifest.task_id).toBe("task_a");
    expect(result.manifest.cleanup_status).toBe("active");
    expect(result.timing).toMatchObject({
      phase: "worktree_setup",
      duration_ms: expect.any(Number)
    });
  });
});
```

- [ ] **Step 2: Update task executor test**

In `packages/orchestrator/tests/taskExecutor.test.ts`, add these expectations:

```ts
    expect(result.phase_timings.map((timing) => timing.phase)).toEqual(
      expect.arrayContaining(["worktree_setup", "provider", "verification", "checkpoint", "checkpoint_dry_run", "total"])
    );
    expect(result.phase_timings.every((timing) => typeof timing.duration_ms === "number")).toBe(true);
```

- [ ] **Step 3: Run focused tests and verify they fail**

Run:

```bash
bun test packages/orchestrator/tests/worktreeManager.test.ts packages/orchestrator/tests/taskExecutor.test.ts
```

Expected: FAIL because `worktreeManager.ts` and `phase_timings` do not exist.

- [ ] **Step 4: Implement WorktreeManager**

Move the worktree preparation helpers from `taskExecutor.ts` into `packages/orchestrator/src/worktreeManager.ts` and expose this API:

```ts
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import type { ExecutionPhaseTiming, WaygentWorktreeManifest } from "@waygent/contracts";
import { buildWorktreeManifest, planWorktree } from "@waygent/kernel-client";

export interface PrepareManagedTaskWorktreeInput {
  run_id: string;
  task_id: string;
  workspace: string;
  worktree_root: string;
}

export interface PreparedManagedTaskWorktree {
  manifest: WaygentWorktreeManifest;
  timing: ExecutionPhaseTiming;
}

export function prepareManagedTaskWorktree(input: PrepareManagedTaskWorktreeInput): PreparedManagedTaskWorktree {
  const startedAtMs = performance.now();
  const started = new Date().toISOString();
  const taskWorktree = planWorktree({
    run_id: input.run_id,
    task_id: input.task_id,
    workspace: input.workspace,
    worktree_root: input.worktree_root
  });
  prepareTaskWorktree(input.workspace, taskWorktree.path);
  const completed = new Date().toISOString();
  return {
    manifest: buildWorktreeManifest({
      ...taskWorktree,
      task_id: input.task_id,
      source_commit: currentGitHead(input.workspace)
    }),
    timing: {
      phase: "worktree_setup",
      started,
      completed,
      duration_ms: Math.round(performance.now() - startedAtMs)
    }
  };
}

export function currentGitHead(workspace: string): string | null {
  const head = spawnSync("git", ["rev-parse", "HEAD"], {
    cwd: workspace,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"]
  });
  return head.status === 0 ? head.stdout.trim() : null;
}

function prepareTaskWorktree(source: string, target: string): void {
  rmSync(target, { recursive: true, force: true });
  mkdirSync(dirname(target), { recursive: true });
  if (!isGitWorktree(source)) {
    mkdirSync(target, { recursive: true });
    cpSync(source, target, { recursive: true, force: true });
    initGitSnapshot(target);
    return;
  }
  const clone = spawnSync("git", ["clone", "--quiet", "--shared", source, target], {
    cwd: source,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (clone.status !== 0) {
    throw new Error(`failed to create task worktree at ${target}: ${clone.stderr}`);
  }
  spawnSync("git", ["checkout", "--detach", "HEAD"], {
    cwd: target,
    encoding: "utf8",
    stdio: ["ignore", "ignore", "ignore"]
  });
  const reset = spawnSync("git", ["reset", "--hard", "HEAD"], {
    cwd: target,
    encoding: "utf8",
    stdio: ["ignore", "ignore", "pipe"]
  });
  if (reset.status !== 0) {
    throw new Error(`failed to prepare task worktree at ${target}: ${reset.stderr}`);
  }
}

function isGitWorktree(source: string): boolean {
  const result = spawnSync("git", ["rev-parse", "--is-inside-work-tree"], {
    cwd: source,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"]
  });
  return result.status === 0 && result.stdout.trim() === "true";
}

function initGitSnapshot(target: string): void {
  spawnSync("git", ["init"], { cwd: target, encoding: "utf8", stdio: ["ignore", "ignore", "ignore"] });
  spawnSync("git", ["add", "."], { cwd: target, encoding: "utf8", stdio: ["ignore", "ignore", "ignore"] });
  spawnSync("git", ["commit", "-m", "initial"], {
    cwd: target,
    encoding: "utf8",
    stdio: ["ignore", "ignore", "ignore"],
    env: {
      ...process.env,
      GIT_AUTHOR_NAME: "Waygent",
      GIT_AUTHOR_EMAIL: "waygent@example.invalid",
      GIT_COMMITTER_NAME: "Waygent",
      GIT_COMMITTER_EMAIL: "waygent@example.invalid"
    }
  });
}
```

- [ ] **Step 5: Refactor task executor**

In `packages/orchestrator/src/taskExecutor.ts`:

1. Import `ExecutionPhaseTiming` and `prepareManagedTaskWorktree`.
2. Remove the local `prepareTaskWorktree`, `isGitWorktree`, `initGitSnapshot`, and `currentGitHead` helpers.
3. Add `phase_timings: ExecutionPhaseTiming[]` to `WaygentTaskExecutionResult`.
4. Replace worktree setup with:

```ts
  const managedWorktree = prepareManagedTaskWorktree({
    run_id: input.run_id,
    task_id: input.task.id,
    workspace: input.workspace,
    worktree_root: input.worktree_root
  });
  const worktreeManifest = managedWorktree.manifest;
  const taskWorktree = {
    path: worktreeManifest.path,
    branch: worktreeManifest.branch,
    source: worktreeManifest.source
  };
  const phaseTimings: ExecutionPhaseTiming[] = [managedWorktree.timing];
```

Wrap provider, verification, checkpoint, and dry-run sections with `measurePhase`:

```ts
async function measurePhase<T>(phase: ExecutionPhaseTiming["phase"], run: () => Promise<T> | T): Promise<{ value: T; timing: ExecutionPhaseTiming }> {
  const startedAtMs = performance.now();
  const started = new Date().toISOString();
  const value = await run();
  const completed = new Date().toISOString();
  return {
    value,
    timing: { phase, started, completed, duration_ms: Math.round(performance.now() - startedAtMs) }
  };
}
```

Return:

```ts
phase_timings: [
  ...phaseTimings,
  { phase: "total", started, completed, duration_ms: Math.round(performance.now() - startedAtMs) }
],
```

- [ ] **Step 6: Replay timings into run state**

In `packages/orchestrator/src/orchestrator.ts`, update `replayTaskExecutionResult` so it writes:

```ts
      task.phase_timings = result.phase_timings;
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
bun test packages/orchestrator/tests/worktreeManager.test.ts packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/tests/orchestratorParallel.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add packages/orchestrator/src/worktreeManager.ts packages/orchestrator/tests/worktreeManager.test.ts packages/orchestrator/src/taskExecutor.ts packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/orchestratorParallel.test.ts
git commit -m "feat: record Waygent worktree and phase timing"
```

## Task 6: Add Artifact Index Recording

**Files:**
- Create: `packages/orchestrator/src/artifactIndex.ts`
- Create: `packages/orchestrator/tests/artifactIndex.test.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/tests/orchestratorParallel.test.ts`

- [ ] **Step 1: Write artifact index tests**

Create `packages/orchestrator/tests/artifactIndex.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import type { ArtifactReference } from "@waygent/contracts";
import { artifactIndexEntry } from "../src/artifactIndex";

describe("artifact index", () => {
  test("builds deterministic index entries from artifact refs", () => {
    const artifact: ArtifactReference = {
      path: "artifacts/worker/task_a.json",
      sha256: "a".repeat(64),
      byte_length: 27,
      media_type: "application/json"
    };

    expect(artifactIndexEntry({
      artifact,
      producer_phase: "provider",
      task_id: "task_a",
      created_at: "2026-05-22T00:00:00.000Z"
    })).toEqual({
      ref: "artifacts/worker/task_a.json",
      media_type: "application/json",
      sha256: "a".repeat(64),
      byte_length: 27,
      producer_phase: "provider",
      task_id: "task_a",
      created_at: "2026-05-22T00:00:00.000Z"
    });
  });
});
```

Add this expectation to the first test in `packages/orchestrator/tests/orchestratorParallel.test.ts`:

```ts
    expect(state.artifact_index?.map((entry) => entry.producer_phase)).toEqual(
      expect.arrayContaining(["task_packet", "provider", "verification", "checkpoint", "checkpoint_dry_run", "combined_apply"])
    );
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```bash
bun test packages/orchestrator/tests/artifactIndex.test.ts packages/orchestrator/tests/orchestratorParallel.test.ts
```

Expected: FAIL because `artifactIndex.ts` and state artifact entries do not exist.

- [ ] **Step 3: Implement artifact index helper**

Create `packages/orchestrator/src/artifactIndex.ts`:

```ts
import type { ArtifactIndexEntry, ArtifactReference, ExecutionPhaseName } from "@waygent/contracts";

export type ArtifactProducerPhase = ExecutionPhaseName | "task_packet" | "combined_apply" | "decision";

export function artifactIndexEntry(input: {
  artifact: ArtifactReference;
  producer_phase: ArtifactProducerPhase;
  task_id: string | null;
  created_at?: string;
}): ArtifactIndexEntry {
  return {
    ref: input.artifact.path,
    media_type: input.artifact.media_type,
    sha256: input.artifact.sha256,
    byte_length: input.artifact.byte_length,
    producer_phase: input.producer_phase,
    task_id: input.task_id,
    created_at: input.created_at ?? new Date().toISOString()
  };
}

export function mergeArtifactIndex(
  existing: ArtifactIndexEntry[] | undefined,
  incoming: ArtifactIndexEntry[]
): ArtifactIndexEntry[] {
  const byRef = new Map<string, ArtifactIndexEntry>();
  for (const entry of existing ?? []) byRef.set(entry.ref, entry);
  for (const entry of incoming) byRef.set(entry.ref, entry);
  return [...byRef.values()].sort((a, b) => a.ref.localeCompare(b.ref));
}
```

- [ ] **Step 4: Return task artifact entries**

In `packages/orchestrator/src/taskExecutor.ts`:

1. Import `ArtifactIndexEntry` and `artifactIndexEntry`.
2. Add `artifact_index_entries: ArtifactIndexEntry[]` to `WaygentTaskExecutionResult`.
3. Create `const artifactIndexEntries: ArtifactIndexEntry[] = [];`.
4. After each `writeArtifact`, push an index entry:

```ts
  artifactIndexEntries.push(artifactIndexEntry({ artifact: packetArtifact, producer_phase: "task_packet", task_id: input.task.id }));
  artifactIndexEntries.push(artifactIndexEntry({ artifact: stdinArtifact, producer_phase: "provider", task_id: input.task.id }));
  artifactIndexEntries.push(artifactIndexEntry({ artifact: workerArtifact, producer_phase: "provider", task_id: input.task.id }));
  artifactIndexEntries.push(artifactIndexEntry({ artifact: stdoutArtifact, producer_phase: "provider", task_id: input.task.id }));
  artifactIndexEntries.push(artifactIndexEntry({ artifact: stderrArtifact, producer_phase: "provider", task_id: input.task.id }));
```

For kernel artifacts:

```ts
      artifactIndexEntries.push(artifactIndexEntry({ artifact: kernelArtifact, producer_phase: "verification", task_id: input.task.id }));
```

For checkpoint and dry-run artifacts, update `CheckpointDryRunResult` in Task 6 Step 5 first, then push:

```ts
      artifactIndexEntries.push(
        artifactIndexEntry({
          artifact: {
            path: checkpoint.manifest_ref,
            sha256: checkpoint.manifest_sha256,
            byte_length: checkpoint.manifest_byte_length,
            media_type: "application/json"
          },
          producer_phase: "checkpoint",
          task_id: input.task.id
        })
      );
      artifactIndexEntries.push(
        artifactIndexEntry({
          artifact: {
            path: checkpoint.patch_ref,
            sha256: checkpoint.patch_sha256,
            byte_length: checkpoint.patch_byte_length,
            media_type: "text/x-diff"
          },
          producer_phase: "checkpoint",
          task_id: input.task.id
        })
      );
      artifactIndexEntries.push(artifactIndexEntry({ artifact: dryRun.evidence_artifact, producer_phase: "checkpoint_dry_run", task_id: input.task.id }));
```

Return `artifact_index_entries: artifactIndexEntries`.

- [ ] **Step 5: Return artifact metadata from checkpoint helpers**

In `packages/orchestrator/src/checkpointArtifacts.ts`, import the artifact type:

```ts
import type { ArtifactReference } from "@waygent/contracts";
```

Then update return interfaces:

```ts
export interface CreatedCheckpointArtifact {
  status: "created";
  manifest_ref: string;
  manifest_sha256: string;
  manifest_byte_length: number;
  patch_ref: string;
  patch_sha256: string;
  patch_byte_length: number;
}

export interface CheckpointDryRunResult {
  status: "passed" | "failed";
  reason?: "checkpoint_unresolvable" | "patch_dry_run_failed";
  evidence_ref: string;
  evidence_artifact: ArtifactReference;
}

export interface CombinedCheckpointPatchResult {
  status: "passed" | "failed";
  checkpoint_refs: string[];
  patch_ref?: string;
  patch_sha256?: string;
  patch_byte_length?: number;
  patch_artifact?: ArtifactReference;
  reason?:
    | CheckpointValidationResult["reason"]
    | "missing_verified_checkpoint"
    | "checkpoint_worktree_missing"
    | "patch_materialization_failed"
    | "patch_dry_run_failed";
  evidence_ref: string;
  evidence_artifact: ArtifactReference;
}
```

Return manifest metadata from `createCheckpointArtifact`:

```ts
    manifest_ref: manifestArtifact.path,
    manifest_sha256: manifestArtifact.sha256,
    manifest_byte_length: manifestArtifact.byte_length,
```

Change `writeCheckpointDryRunEvidence` so it returns `ArtifactReference` instead of `string`, and update callers to set:

```ts
return { status, evidence_ref: evidence.path, evidence_artifact: evidence };
```

Change `writeCombinedPatchEvidence` so it returns `ArtifactReference` instead of `string`. In `createCombinedCheckpointPatchArtifact`, return:

```ts
    const evidenceArtifact = writeCombinedPatchEvidence(input.run_root, checkpointRefs, {
      status,
      patch_ref: patchArtifact.path,
      stdout: dryRun.stdout,
      stderr: dryRun.stderr
    });
    return {
      status,
      checkpoint_refs: checkpointRefs,
      patch_ref: patchArtifact.path,
      patch_sha256: patchArtifact.sha256,
      patch_byte_length: patchArtifact.byte_length,
      patch_artifact: patchArtifact,
      ...(status === "failed" ? { reason: "patch_dry_run_failed" as const } : {}),
      evidence_ref: evidenceArtifact.path,
      evidence_artifact: evidenceArtifact
    };
```

In `failedCombinedPatch`, return:

```ts
  const evidenceArtifact = writeCombinedPatchEvidence(runRoot, checkpointRefs, {
    status: "failed",
    reason,
    ...payload
  });
  return { status: "failed", checkpoint_refs: checkpointRefs, reason, evidence_ref: evidenceArtifact.path, evidence_artifact: evidenceArtifact };
```

- [ ] **Step 6: Replay artifact index into state**

In `packages/orchestrator/src/orchestrator.ts`, import `mergeArtifactIndex` and update `replayTaskExecutionResult`:

```ts
      state.artifact_index = mergeArtifactIndex(state.artifact_index, result.artifact_index_entries);
```

When combined apply evidence is created, register its patch and evidence refs. Add a small local helper:

```ts
function combinedApplyArtifactEntries(combined: CombinedCheckpointPatchResult | undefined): ArtifactIndexEntry[] {
  if (!combined) return [];
  return [
    combined.patch_artifact
      ? artifactIndexEntry({ artifact: combined.patch_artifact, producer_phase: "combined_apply", task_id: null })
      : null,
    artifactIndexEntry({ artifact: combined.evidence_artifact, producer_phase: "combined_apply", task_id: null })
  ].filter((entry): entry is ArtifactIndexEntry => entry !== null);
}
```

Use it after completion audit creation:

```ts
    state.artifact_index = mergeArtifactIndex(state.artifact_index, combinedApplyArtifactEntries(combinedApplyEvidence));
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
bun test packages/orchestrator/tests/artifactIndex.test.ts packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/tests/orchestratorParallel.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add packages/orchestrator/src/artifactIndex.ts packages/orchestrator/tests/artifactIndex.test.ts packages/orchestrator/src/taskExecutor.ts packages/orchestrator/src/checkpointArtifacts.ts packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/tests/orchestratorParallel.test.ts
git commit -m "feat: index Waygent run artifacts"
```

## Task 7: Use Artifact Index In Reconciliation

**Files:**
- Modify: `packages/orchestrator/src/stateReconciliation.ts`
- Modify: `packages/orchestrator/tests/stateReconciliation.test.ts`
- Modify: `packages/lens-projectors/tests/executionExplanation.test.ts`

- [ ] **Step 1: Add reconciliation tests**

Append this test to `packages/orchestrator/tests/stateReconciliation.test.ts`:

```ts
test("blocks when indexed artifact digest drifts from bytes", () => {
  const fixture = writeReconciliationFixture("run_index_drift");
  const state = readRunStateV2(fixture.root, fixture.runId);
  const indexedRef = state.provider_attempts[0]!.stdout_ref;
  writeRunStateV2(fixture.root, {
    ...state,
    artifact_index: [
      {
        ref: indexedRef,
        media_type: "text/plain",
        sha256: "a".repeat(64),
        byte_length: 12,
        producer_phase: "provider",
        task_id: "task_a",
        created_at: "2026-05-22T00:00:00.000Z"
      }
    ]
  });

  const report = reconcileRunState(fixture.root, fixture.runId);

  expect(report.passed).toBe(false);
  expect(report.records).toContainEqual(expect.objectContaining({
    failure_class: "state_drift",
    artifact_ref: indexedRef
  }));
});
```

- [ ] **Step 2: Run focused test and verify it fails**

Run:

```bash
bun test packages/orchestrator/tests/stateReconciliation.test.ts
```

Expected: FAIL because indexed artifact digest drift is not checked.

- [ ] **Step 3: Add index validation to reconciliation**

In `packages/orchestrator/src/stateReconciliation.ts`, add a validation loop after reading state:

```ts
  for (const entry of state.artifact_index ?? []) {
    const absolute = resolveRunArtifactPath(state.run_root, entry.ref);
    if (!existsSync(absolute)) {
      records.push(missing(`indexed artifact is missing: ${entry.ref}`, entry.ref, entry.task_id ?? undefined));
      continue;
    }
    const bytes = readFileSync(absolute);
    if (sha256(bytes) !== entry.sha256 || bytes.byteLength !== entry.byte_length) {
      records.push(drift(`indexed artifact digest does not match bytes: ${entry.ref}`, entry.ref, entry.task_id ?? undefined));
    }
  }
```

Keep the existing checkpoint, provider, verification, combined patch, and event journal checks. The index check is additive.

- [ ] **Step 4: Add explanation test for drift health**

In `packages/lens-projectors/tests/executionExplanation.test.ts`, add:

```ts
  test("summarizes drift records in artifact health", () => {
    const projection = projectExecutionExplanationFromState(makeState({
      drift: {
        last_checked_at: "2026-05-22T00:00:00.000Z",
        records: [
          { type: "state_drift", failure_class: "state_drift" },
          { type: "artifact_missing", failure_class: "artifact_missing" }
        ],
        unrepaired_blockers: []
      }
    }));

    expect(projection.artifact_health).toMatchObject({
      missing_count: 1,
      drift_count: 1
    });
  });
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
bun test packages/orchestrator/tests/stateReconciliation.test.ts packages/lens-projectors/tests/executionExplanation.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add packages/orchestrator/src/stateReconciliation.ts packages/orchestrator/tests/stateReconciliation.test.ts packages/lens-projectors/tests/executionExplanation.test.ts
git commit -m "feat: reconcile Waygent artifact index"
```

## Task 8: Final Docs And Verification

**Files:**
- Modify: `docs/operations/waygent.md`
- Modify: `docs/architecture/waygent.md`

- [ ] **Step 1: Document operator behavior**

Add this section to `docs/operations/waygent.md` after `Safe-Wave Parallel Execution`:

```md
## Execution Intelligence

`waygent inspect --json` and the console expose execution intelligence from
durable run evidence. The projection explains safe waves, withheld tasks,
barriers, phase timing, artifact health, and next plan-shaping actions.

Execution intelligence is read-only. Apply readiness still comes from
checkpoint manifests, patch digest checks, dry-run evidence, completion audit,
reconciliation, and clean source checkout validation.
```

Add this sentence to `docs/architecture/waygent.md` after the safe-wave design reference:

```md
Execution intelligence is documented in
[`../superpowers/specs/2026-05-22-waygent-execution-intelligence-design.md`](../superpowers/specs/2026-05-22-waygent-execution-intelligence-design.md).
```

- [ ] **Step 2: Run full TypeScript verification**

Run:

```bash
bun run check
bun run waygent:scenarios
bun run platform:demo
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

Expected: all commands PASS.

- [ ] **Step 3: Review final diff**

Run:

```bash
git diff --stat HEAD
git diff -- packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/lens-projectors/src packages/orchestrator/src apps/api/src apps/console/src docs/operations/waygent.md docs/architecture/waygent.md
```

Expected:

- no active AgentRunway or KWS executor routing is introduced;
- `ExecutionExplanationProjection` is read-only;
- artifact index checks are additive and do not replace byte-level validation;
- apply readiness still depends on existing readiness gates.

- [ ] **Step 4: Commit docs and verification updates**

Run:

```bash
git add docs/operations/waygent.md docs/architecture/waygent.md
git commit -m "docs: document Waygent execution intelligence"
```

- [ ] **Step 5: Final status check**

Run:

```bash
git status --short --branch --untracked-files=all
```

Expected: clean worktree except the branch ahead count.

## Final Verification

Run this from the repository root after Task 8:

```bash
bun run check
bun run waygent:scenarios
bun run platform:demo
bun run check:legacy
bun run --cwd apps/console build
git diff --check
git status --short --branch --untracked-files=all
```

Expected:

- TypeScript builds and tests pass.
- Scenario replay passes.
- Platform demo reports a trusted run.
- Legacy guard passes.
- Console production build passes.
- Patch hygiene passes.
- Worktree is clean except branch ahead count.

## Review Checklist

Before reporting completion, review `code_review.md` and confirm:

- execution explanation is a projection and cannot authorize apply;
- artifact index drift keeps reconciliation blocked;
- worktree setup stays isolated per task;
- provider claims still require verification and checkpoint evidence;
- no active AgentRunway or KWS executor routing reappears;
- console handles missing execution explanation data without crashing.
