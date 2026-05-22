# Waygent Runtime Closure Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Waygent runtime closure loop so a run that produces verified work but fails checkpoint dry-run is reported, recovered, and displayed as a precise source-basis conflict, while CLI, API, console, and provider diagnostics all read the same v2 truth.

**Architecture:** Keep `waygent.run_state.v2` and checkpoint evidence as the runtime source of truth. Land the shared core sequentially: checkpoint dry-run classification, task-state recovery wiring, and a pure shared run-read projector. Once that projector is stable, API and console can move in parallel while consuming the same classification. Provider cost/noise refinements remain read-only projections and must not weaken apply readiness.

**Tech Stack:** Bun, TypeScript, React, Vite, `bun:test`, Waygent contracts, Waygent lens projectors, Waygent orchestrator, Waygent testkit, Graphify.

---

## Context

Design spec: `docs/superpowers/specs/2026-05-22-waygent-runtime-closure-loop-design.md`

Observed runtime gap from the latest real Codex-backed Waygent run:

- provider execution succeeded and produced a normalized worker result;
- kernel verification passed;
- checkpoint manifest and patch artifacts were written;
- checkpoint dry-run failed because `git apply --check` could not apply the patch to the current source checkout;
- v2 task state reported `status: "verified"`, `latest_failure_class: "missing_checkpoint"`, and `checkpoint_refs: []`;
- `waygent explain --last` reported `missing_checkpoint`, hiding the actual checkpoint conflict;
- provider runtime dominated total runtime, and provider stderr contained high plugin/skill-loader startup noise.

Relevant anchors:

- `packages/orchestrator/src/checkpointArtifacts.ts` owns checkpoint manifest validation, patch materialization, dry-run evidence, and combined apply patches.
- `packages/orchestrator/src/taskExecutor.ts` currently maps failed checkpoint dry-run to `missing_checkpoint` and can return `verified` with a non-null failure class.
- `packages/orchestrator/src/runCommands.ts` currently computes `statusRun` from events before `inspectRun` loads v2 state.
- `apps/api/src/server.ts` duplicates real-run summary logic and computes list status from events before detail overrides from v2 state.
- `apps/console/src/uiModel.ts` trusts API summary/detail fields and must not infer apply readiness independently.
- `packages/lens-projectors/src/runtimeCost.ts`, `providerReadiness.ts`, and `operationalMaturity.ts` already expose operator projections and are the right place for bounded provider diagnostics.

Out of scope:

- Do not weaken checkpoint manifests, patch digest checks, completion audit, reconciliation, combined patch evidence, or clean-checkout apply rules.
- Do not enable apply from provider success alone.
- Do not replace v2 state with event-derived readiness when v2 state exists.
- Do not run live Codex or Claude smoke tests by default.
- Do not reintroduce AgentRunway, KWS CPE, or KWS CME routing.
- Do not automatically mutate source files from recovery recommendations.

## File Structure

- `packages/contracts/src/types.ts`: add stable projection types for the shared run-read model and structured checkpoint dry-run failure shape if needed by API/console contracts.
- `packages/lens-projectors/src/runReadModel.ts`: new pure projector for CLI/API/console run status, apply status, trust status, state errors, and top blocker.
- `packages/lens-projectors/src/runtimeCost.ts`: add provider-dominated and provider-noise recommendations.
- `packages/lens-projectors/src/providerReadiness.ts`: keep successful noisy providers ready while recommending startup-noise cleanup separately.
- `packages/lens-projectors/src/operationalMaturity.ts`: make hard blockers and next actions include checkpoint dry-run conflicts with precise summaries.
- `packages/lens-projectors/src/index.ts`: export the new projector.
- `packages/lens-projectors/tests/runReadModel.test.ts`: unit tests for shared v2-first status projection.
- `packages/lens-projectors/tests/operationalMaturity.test.ts`: provider cost/noise and checkpoint-conflict projection tests.
- `packages/orchestrator/src/checkpointArtifacts.ts`: classify patch dry-run failures and persist failed files/evidence details.
- `packages/orchestrator/src/taskExecutor.ts`: record dry-run conflict failure classes in v2 state and block tasks with failed dry-run.
- `packages/orchestrator/src/recoveryExecutor.ts`: route `needs_rebase` checkpoint conflicts to checkpoint regeneration or human decision, not apply.
- `packages/orchestrator/src/runCommands.ts`: consume the shared run-read projector and improve explain/resume text for checkpoint conflicts.
- `packages/orchestrator/tests/checkpointArtifacts.test.ts`: dry-run conflict fixture.
- `packages/orchestrator/tests/taskExecutor.test.ts`: regression for blocked task state when checkpoint dry-run fails after verification.
- `packages/orchestrator/tests/runCommandsV2.test.ts`: explain/resume/status behavior for `needs_rebase`.
- `packages/orchestrator/tests/runCommands.test.ts`: adjust event-only fallback expectations if needed.
- `apps/api/src/server.ts`: use the shared run-read projector for list/detail parity.
- `apps/api/tests/api.test.ts`: assert CLI/API parity for blocked v2 status and apply readiness.
- `apps/console/src/uiModel.ts`: surface shared status, apply readiness, blocker, provider hotspot, and provider-noise summary without local inference.
- `apps/console/src/uiModel.test.ts`: list/detail parity and apply-button guard tests.
- `packages/testkit/src/waygentScenarioHarness.ts`: add a deterministic checkpoint dry-run conflict fixture mode.
- `packages/testkit/tests/waygentScenarioHarness.test.ts`: normalize the conflict blocker and failure class.
- `tests/waygent-scenarios/checkpoint-dry-run-conflict.json`: replayable blocked fixture.
- `tests/integration/waygent-scenarios.test.ts`: expected replay for the new fixture.
- `docs/operations/waygent.md`: operator-facing closure-loop behavior.
- `docs/operations/verification.md`: verification commands and conflict fixture coverage.
- `docs/architecture/waygent.md`: runtime truth source and projection boundary update if current architecture docs mention run reads.
- `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`: refresh after code and docs changes.

## Waygent Task Packet

```yaml waygent-task
id: task_waygent_runtime_closure_loop
title: Implement Waygent Runtime Closure Loop
dependencies: []
file_claims:
  - path: packages/contracts/src/types.ts
    mode: edit
  - path: packages/lens-projectors/src/runReadModel.ts
    mode: owned
  - path: packages/lens-projectors/src/runtimeCost.ts
    mode: edit
  - path: packages/lens-projectors/src/providerReadiness.ts
    mode: edit
  - path: packages/lens-projectors/src/operationalMaturity.ts
    mode: edit
  - path: packages/lens-projectors/src/index.ts
    mode: edit
  - path: packages/lens-projectors/tests/runReadModel.test.ts
    mode: owned
  - path: packages/lens-projectors/tests/operationalMaturity.test.ts
    mode: edit
  - path: packages/orchestrator/src/checkpointArtifacts.ts
    mode: edit
  - path: packages/orchestrator/src/taskExecutor.ts
    mode: edit
  - path: packages/orchestrator/src/recoveryExecutor.ts
    mode: edit
  - path: packages/orchestrator/src/runCommands.ts
    mode: edit
  - path: packages/orchestrator/tests/checkpointArtifacts.test.ts
    mode: edit
  - path: packages/orchestrator/tests/taskExecutor.test.ts
    mode: edit
  - path: packages/orchestrator/tests/runCommandsV2.test.ts
    mode: edit
  - path: packages/orchestrator/tests/runCommands.test.ts
    mode: edit
  - path: apps/api/src/server.ts
    mode: edit
  - path: apps/api/tests/api.test.ts
    mode: edit
  - path: apps/console/src/uiModel.ts
    mode: edit
  - path: apps/console/src/uiModel.test.ts
    mode: edit
  - path: packages/testkit/src/waygentScenarioHarness.ts
    mode: edit
  - path: packages/testkit/tests/waygentScenarioHarness.test.ts
    mode: edit
  - path: tests/waygent-scenarios/checkpoint-dry-run-conflict.json
    mode: owned
  - path: docs/operations/waygent.md
    mode: edit
  - path: docs/operations/verification.md
    mode: edit
  - path: docs/architecture/waygent.md
    mode: edit
  - path: graphify-out/GRAPH_REPORT.md
    mode: owned
  - path: graphify-out/graph.json
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/checkpointArtifacts.test.ts packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/tests/runCommandsV2.test.ts
  - bun test packages/lens-projectors/tests/runReadModel.test.ts packages/lens-projectors/tests/operationalMaturity.test.ts packages/provider-adapters/tests/providerLogSummary.test.ts
  - bun test apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts packages/testkit/tests/waygentScenarioHarness.test.ts
  - bun run check
  - bun run waygent:scenarios
  - bun run waygent:dogfood
  - bun run check:legacy
  - bun run --cwd apps/console build
  - git diff --check
```

## Task Breakdown

```yaml
id: T1
title: Classify checkpoint dry-run conflicts with structured evidence
owner_boundary: packages/orchestrator checkpoint artifacts
files:
  - path: packages/orchestrator/src/checkpointArtifacts.ts
    mode: edit
  - path: packages/orchestrator/tests/checkpointArtifacts.test.ts
    mode: edit
acceptance:
  - command: bun test packages/orchestrator/tests/checkpointArtifacts.test.ts
  - expected: dry-run conflict fixture reports reason patch_dry_run_failed, failure_class needs_rebase, failed_files, and persisted evidence
risks:
  - Regex classification can overfit git stderr. Keep unrecognized patch failures blocked as unsafe_apply with raw evidence preserved.
```

### T1 Steps

- [ ] Add a failing conflict fixture in `packages/orchestrator/tests/checkpointArtifacts.test.ts`.

Use a real repo, create the checkpoint from a cloned worktree, mutate the source checkout after checkpoint creation, then run `dryRunCheckpointPatch` against the changed source:

```ts
test("classifies checkpoint dry-run source conflicts as needs_rebase", () => {
  const runRoot = mkdtempSync(join(tmpdir(), "waygent-checkpoint-conflict-run-"));
  const source = initRepo("waygent-checkpoint-conflict-source-");
  const worktree = cloneWorktree(source, "waygent-checkpoint-conflict-worktree-");
  writeFileSync(join(worktree, "README.md"), "candidate change\n");

  const checkpoint = createCheckpointArtifact({
    run_root: runRoot,
    run_id: "run_conflict",
    task_id: "task_conflict",
    candidate_id: "candidate_conflict",
    worktree_path: worktree,
    changed_files: ["README.md"],
    verification_refs: []
  });

  writeFileSync(join(source, "README.md"), "source moved\n");
  const dryRun = dryRunCheckpointPatch({
    run_root: runRoot,
    checkpoint_ref: checkpoint.manifest_ref,
    source
  });

  expect(dryRun).toMatchObject({
    status: "failed",
    reason: "patch_dry_run_failed",
    failure_class: "needs_rebase",
    failed_files: ["README.md"]
  });
  const evidence = JSON.parse(readFileSync(join(runRoot, dryRun.evidence_ref), "utf8"));
  expect(evidence).toMatchObject({
    status: "failed",
    reason: "patch_dry_run_failed",
    failure_class: "needs_rebase",
    failed_files: ["README.md"]
  });
  expect(readCheckpointManifest(runRoot, checkpoint.manifest_ref)).toMatchObject({
    dry_run_status: "failed",
    dry_run_evidence_ref: dryRun.evidence_ref
  });
});
```

- [ ] Extend `CheckpointDryRunResult` with a failure class and failed files.

Keep the public status/reason fields stable and add optional fields:

```ts
import type { ArtifactReference, FailureClass } from "@waygent/contracts";

export interface CheckpointDryRunResult {
  status: "passed" | "failed";
  reason?: "checkpoint_unresolvable" | "patch_dry_run_failed";
  failure_class?: Extract<FailureClass, "missing_checkpoint" | "needs_rebase" | "unsafe_apply">;
  failed_files?: string[];
  no_op?: boolean;
  evidence_ref: string;
  evidence_artifact: ArtifactReference;
}
```

- [ ] Add a small classifier in `checkpointArtifacts.ts`.

The first pass only needs to classify standard `git apply --check` conflict output:

```ts
export function classifyCheckpointDryRunFailure(stderr: string): {
  failure_class: Extract<FailureClass, "needs_rebase" | "unsafe_apply">;
  failed_files: string[];
} {
  const failedFiles = [...stderr.matchAll(/^error: patch failed: (.+?):\d+/gm)]
    .map((match) => match[1])
    .filter((value): value is string => typeof value === "string" && value.length > 0);
  const doesNotApply = /patch does not apply|patch failed/i.test(stderr);
  return {
    failure_class: doesNotApply ? "needs_rebase" : "unsafe_apply",
    failed_files: [...new Set(failedFiles)]
  };
}
```

- [ ] Attach classification to dry-run return values and evidence JSON.

Inside `dryRunCheckpointPatch`, compute the classifier only when `status === "failed"`:

```ts
const classification = status === "failed"
  ? classifyCheckpointDryRunFailure(dryRun.stderr)
  : null;
const evidence = writeCheckpointDryRunEvidence(input.run_root, input.checkpoint_ref, {
  status,
  stdout: dryRun.stdout,
  stderr: dryRun.stderr,
  ...(classification ? {
    reason: "patch_dry_run_failed",
    failure_class: classification.failure_class,
    failed_files: classification.failed_files
  } : {})
});

return {
  status,
  ...(status === "failed" ? { reason: "patch_dry_run_failed" as const } : {}),
  ...(classification ?? {}),
  evidence_ref: evidence.path,
  evidence_artifact: evidence
};
```

For `checkpoint_unresolvable`, return `failure_class: "missing_checkpoint"` and evidence with the same value.

```yaml
id: T2
title: Wire checkpoint conflict classification into task state, explain, and resume
owner_boundary: packages/orchestrator task execution and recovery commands
files:
  - path: packages/orchestrator/src/taskExecutor.ts
    mode: edit
  - path: packages/orchestrator/src/recoveryExecutor.ts
    mode: edit
  - path: packages/orchestrator/src/runCommands.ts
    mode: edit
  - path: packages/orchestrator/tests/taskExecutor.test.ts
    mode: edit
  - path: packages/orchestrator/tests/runCommandsV2.test.ts
    mode: edit
acceptance:
  - command: bun test packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/tests/runCommandsV2.test.ts
  - expected: failed checkpoint dry-run blocks the task as needs_rebase, explain names dry-run evidence, resume does not offer apply
risks:
  - Changing task status from verified to blocked can update downstream snapshots. Update only tests that were relying on the incorrect verified-with-failure state.
```

### T2 Steps

- [ ] Update `executeWaygentTask` so failed checkpoint dry-run uses the dry-run failure class.

Replace the current `latestFailureClass = "missing_checkpoint"` assignment in the dry-run failure branch:

```ts
if (dryRun.status === "passed") {
  checkpointRefs.push(checkpoint.manifest_ref);
} else {
  latestFailureClass = dryRun.failure_class ?? "unsafe_apply";
}
```

Return blocked when any failure class remains:

```ts
return {
  task_id: input.task.id,
  status: verificationPassed && latestFailureClass === null ? "verified" : "blocked",
  latest_failure_class: latestFailureClass,
  checkpoint_refs: checkpointRefs,
  // existing fields remain unchanged
};
```

- [ ] Keep the dry-run event payload structured.

The existing event should retain `dry_run` as the full result:

```ts
events.push({
  run_id: input.run_id,
  event_type: "runway.apply_dry_run_result",
  phase: "checkpoint",
  outcome: dryRun.status === "passed" ? "success" : "blocked",
  summary: dryRun.status === "passed"
    ? "Checkpoint patch dry-run passed."
    : "Checkpoint patch dry-run failed.",
  payload: {
    task_id: input.task.id,
    checkpoint_ref: checkpoint.manifest_ref,
    dry_run: dryRun
  },
  trust_impact: dryRun.status === "passed" ? "supports_success" : "supports_failure"
});
```

- [ ] Change `needs_rebase` recovery from source cleanup to checkpoint regeneration.

In `packages/orchestrator/src/recoveryExecutor.ts`, keep `dirty_source_checkout` on `clean_source_checkout`, and route `needs_rebase` with checkpoint/state-drift blockers:

```ts
if (
  input.failure_class === "missing_checkpoint" ||
  input.failure_class === "artifact_missing" ||
  input.failure_class === "state_drift" ||
  input.failure_class === "needs_rebase"
) {
  return input.retry_count < input.max_retries
    ? { action: "retry_checkpoint_generation", automatic: true }
    : { action: "human_decision", automatic: false };
}
if (input.failure_class === "dirty_source_checkout") {
  return { action: "clean_source_checkout", automatic: false };
}
```

- [ ] Improve `explainRun` for checkpoint dry-run conflicts.

Add a helper in `runCommands.ts` that reads the latest dry-run event for the task and builds a short summary:

```ts
function checkpointDryRunConflictSummary(events: AgentLensEvent[], taskId: string): string | null {
  const event = [...events].reverse().find((candidate) =>
    candidate.event_type === "runway.apply_dry_run_result" &&
    candidate.payload?.task_id === taskId
  );
  const dryRun = event?.payload?.dry_run;
  if (!dryRun || typeof dryRun !== "object") return null;
  const record = dryRun as Record<string, unknown>;
  if (record.failure_class !== "needs_rebase") return null;
  const files = Array.isArray(record.failed_files)
    ? record.failed_files.filter((value): value is string => typeof value === "string")
    : [];
  const fileSuffix = files.length > 0 ? `; files: ${files.join(", ")}` : "";
  return `checkpoint patch dry-run failed against current source${fileSuffix}`;
}
```

Use it when building `summaryParts`:

```ts
const conflictSummary = stateFailure
  ? checkpointDryRunConflictSummary(events, stateFailure.task_id)
  : null;
const summaryParts = [
  activeFailure
    ? `${activeFailure.task_id} blocked by ${activeFailure.failure_class}${conflictSummary ? `: ${conflictSummary}` : ""}`
    : "no active failure barrier",
  // existing barrier/hotspot/dogfood parts
].filter(Boolean);
```

- [ ] Add a v2 command regression for the precise blocker.

In `packages/orchestrator/tests/runCommandsV2.test.ts`, create blocked v2 state plus a dry-run event:

```ts
test("explain and resume report checkpoint dry-run conflicts as needs_rebase", () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-run-needs-rebase-"));
  const runId = "run_needs_rebase";
  writeRunStateV2(root, {
    // normal v2 envelope fields
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
    status: "blocked",
    lifecycle_outcome: "blocked",
    current_phase: "recover",
    safe_waves: [],
    tasks: {
      task_conflict: {
        id: "task_conflict",
        status: "blocked",
        risk: "low",
        dependencies: [],
        file_claims: [{ path: "README.md", mode: "owned" }],
        attempts: [],
        task_packet_path: null,
        task_packet_sha256: null,
        unit_manifest: { allowed_write_globs: ["README.md"] },
        checkpoint_refs: [],
        latest_failure_class: "needs_rebase",
        decision_packet_ref: null,
        timing: {}
      }
    },
    provider_attempts: [],
    reviews: [],
    verification: [],
    recovery: [],
    apply: { status: "blocked", reason: "needs_rebase" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: null,
    timestamps: {
      started_at: "2026-05-22T00:00:00.000Z",
      updated_at: "2026-05-22T00:00:01.000Z",
      completed_at: null
    }
  });
  appendEvent(join(root, runId, "events.jsonl"), buildRunEvent({
    run_id: runId,
    sequence: 1,
    event_type: "runway.apply_dry_run_result",
    phase: "checkpoint",
    outcome: "blocked",
    summary: "Checkpoint patch dry-run failed.",
    payload: {
      task_id: "task_conflict",
      checkpoint_ref: "artifacts/checkpoints/task_conflict/candidate_task_conflict.json",
      dry_run: {
        status: "failed",
        reason: "patch_dry_run_failed",
        failure_class: "needs_rebase",
        failed_files: ["README.md"],
        evidence_ref: "artifacts/checkpoints/task_conflict/dry-run.json"
      }
    }
  }));

  const explanation = explainRun({ root, run: runId });
  expect(explanation.blocked_by).toBe("needs_rebase");
  expect(explanation.summary).toContain("checkpoint patch dry-run failed");
  expect(explanation.summary).toContain("README.md");
  expect(resumeRun({ root, run: runId, dry_run: true }).allowed_actions).toEqual(["retry_checkpoint_generation"]);
});
```

```yaml
id: T3
title: Add one shared v2-first run-read model
owner_boundary: packages/contracts and packages/lens-projectors
files:
  - path: packages/contracts/src/types.ts
    mode: edit
  - path: packages/lens-projectors/src/runReadModel.ts
    mode: owned
  - path: packages/lens-projectors/src/index.ts
    mode: edit
  - path: packages/lens-projectors/tests/runReadModel.test.ts
    mode: owned
  - path: packages/orchestrator/src/runCommands.ts
    mode: edit
acceptance:
  - command: bun test packages/lens-projectors/tests/runReadModel.test.ts packages/orchestrator/tests/runCommandsV2.test.ts packages/orchestrator/tests/runCommands.test.ts
  - expected: statusRun, inspectRun, and projector tests prefer v2 state over events and expose state errors explicitly
risks:
  - API cannot import orchestrator without creating a dependency inversion. Put the pure projector in lens-projectors and let each runtime layer provide its own state-read adapter.
```

### T3 Steps

- [ ] Add contract types for a shared run-read projection.

In `packages/contracts/src/types.ts`:

```ts
export type WaygentRunStateReadErrorReason =
  | "missing_run_state_v2"
  | "unsupported_run_state"
  | "invalid_run_state_v2";

export interface WaygentRunStateReadError {
  status: "missing" | "unsupported" | "invalid";
  reason: WaygentRunStateReadErrorReason;
  schema?: string | null;
  error?: string;
}

export interface RunReadModelProjection {
  schema: "waygent.run_read_model.v1";
  run_id: string;
  status: RunStatus;
  trust_status: "trusted" | "failed" | "insufficient_evidence";
  apply_status: ApplyReadinessProjection["status"];
  apply_readiness: ApplyReadinessProjection | null;
  total_events: number;
  last_event_type: string | null;
  top_blocker: {
    task_id: string | null;
    failure_class: FailureClass | string;
    summary: string;
  } | null;
  state_error: WaygentRunStateReadError | null;
}
```

- [ ] Create `packages/lens-projectors/src/runReadModel.ts`.

This module must be pure and import only contracts plus other lens projectors:

```ts
import type {
  AgentLensEvent,
  RunReadModelProjection,
  RunStatus,
  WaygentRunStateReadError,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectApplyReadinessFromState } from "./apply";
import { projectOperationalMaturityFromState } from "./operationalMaturity";
import { projectTrustReport } from "./trust";

export type RunReadStateInput =
  | { status: "ok"; state: WaygentRunStateV2 }
  | WaygentRunStateReadError;

export function projectRunReadModel(input: {
  run_id: string;
  events: AgentLensEvent[];
  state_result: RunReadStateInput;
}): RunReadModelProjection {
  const trust = projectTrustReport(input.events);
  const lastEventType = input.events.at(-1)?.event_type ?? null;
  if (input.state_result.status === "ok") {
    const state = input.state_result.state;
    const readiness = projectApplyReadinessFromState(state);
    const maturity = projectOperationalMaturityFromState({ state, events: input.events });
    return {
      schema: "waygent.run_read_model.v1",
      run_id: input.run_id,
      status: runStatusFromV2(state.status),
      trust_status: trust.trust_status,
      apply_status: readiness.status,
      apply_readiness: readiness,
      total_events: input.events.length,
      last_event_type: lastEventType,
      top_blocker: maturity.hard_blocker,
      state_error: null
    };
  }

  const fallbackStatus = input.state_result.status === "missing"
    ? runStatusFromEvents(input.events, trust.trust_status)
    : "blocked";
  return {
    schema: "waygent.run_read_model.v1",
    run_id: input.run_id,
    status: fallbackStatus,
    trust_status: trust.trust_status,
    apply_status: "not_ready",
    apply_readiness: null,
    total_events: input.events.length,
    last_event_type: lastEventType,
    top_blocker: {
      task_id: null,
      failure_class: input.state_result.reason,
      summary: `run blocked by ${input.state_result.reason}`
    },
    state_error: input.state_result
  };
}

function runStatusFromV2(status: WaygentRunStateV2["status"]): RunStatus {
  if (status === "initializing") return "pending";
  if (status === "applying") return "running";
  return status;
}

function runStatusFromEvents(
  events: AgentLensEvent[],
  trustStatus: RunReadModelProjection["trust_status"]
): RunStatus {
  if (events.some((event) => event.event_type === "runway.apply_completed")) return "applied";
  if (events.some((event) => event.outcome === "blocked")) return "blocked";
  if (events.some((event) => event.outcome === "failed")) return "failed";
  return trustStatus === "trusted" ? "completed" : "running";
}
```

- [ ] Export the projector from `packages/lens-projectors/src/index.ts`.

```ts
export * from "./runReadModel";
```

- [ ] Add `packages/lens-projectors/tests/runReadModel.test.ts`.

Cover three cases:

```ts
test("prefers blocked v2 state over trusted events", () => {
  const model = projectRunReadModel({
    run_id: "run_v2_blocked",
    events: trustedEvents("run_v2_blocked"),
    state_result: { status: "ok", state: blockedState("run_v2_blocked", "needs_rebase") }
  });
  expect(model.status).toBe("blocked");
  expect(model.apply_status).toBe("blocked");
  expect(model.top_blocker?.failure_class).toBe("needs_rebase");
});

test("falls back to event status only when v2 state is missing", () => {
  const model = projectRunReadModel({
    run_id: "run_event_only",
    events: trustedEvents("run_event_only"),
    state_result: { status: "missing", reason: "missing_run_state_v2" }
  });
  expect(model.status).toBe("completed");
  expect(model.apply_status).toBe("not_ready");
  expect(model.state_error?.reason).toBe("missing_run_state_v2");
});

test("blocks unsupported or invalid v2 state", () => {
  const model = projectRunReadModel({
    run_id: "run_bad_state",
    events: trustedEvents("run_bad_state"),
    state_result: { status: "unsupported", reason: "unsupported_run_state", schema: "waygent.run_state.v1" }
  });
  expect(model.status).toBe("blocked");
  expect(model.top_blocker?.failure_class).toBe("unsupported_run_state");
});
```

- [ ] Wire `statusRun` and `inspectRun` to `projectRunReadModel`.

Create a small adapter in `runCommands.ts`:

```ts
function toRunReadStateInput(result: RunStateV2ReadResult): RunReadStateInput {
  if (result.status === "ok") return { status: "ok", state: result.state };
  if (result.reason === "missing_run_state_v2") return { status: "missing", reason: result.reason };
  if (result.reason === "unsupported_run_state") return { status: "unsupported", reason: result.reason, schema: String(result.schema ?? "") };
  return { status: "invalid", reason: result.reason, error: result.error };
}
```

Then compute status from the shared model:

```ts
export function statusRun(options: RunCommandOptions): RunStatusView {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  const stateResult = readRunStateV2Result(options.root, runId);
  const model = projectRunReadModel({
    run_id: runId,
    events,
    state_result: toRunReadStateInput(stateResult)
  });
  return {
    run_id: runId,
    status: model.status,
    total_events: model.total_events,
    last_event_type: model.last_event_type,
    trust_status: model.trust_status
  };
}
```

`inspectRun` should include `run_read_model: model` and reuse the already-read `stateResult` rather than reading v2 state twice.

```yaml
id: T4
title: Align API and console with the shared run-read model
owner_boundary: apps/api and apps/console
files:
  - path: apps/api/src/server.ts
    mode: edit
  - path: apps/api/tests/api.test.ts
    mode: edit
  - path: apps/console/src/uiModel.ts
    mode: edit
  - path: apps/console/src/uiModel.test.ts
    mode: edit
acceptance:
  - command: bun test apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts
  - expected: API list/detail and console list/detail agree with CLI status/apply readiness for blocked v2 runs
risks:
  - Console presentation code can drift if it infers state from event names. Keep all summary fields data-driven from API response fields.
```

### T4 Steps

- [ ] Replace API real-run summary status logic with `projectRunReadModel`.

In `apps/api/src/server.ts`, keep local file reading but return a state-read union that matches `RunReadStateInput`:

```ts
function readApiRunStateResult(runRoot: string, runId: string): RunReadStateInput {
  try {
    const parsed = JSON.parse(readFileSync(join(runPaths(runRoot, runId).root, "state.json"), "utf8")) as { schema?: string };
    if (parsed.schema !== "waygent.run_state.v2") {
      return { status: "unsupported", reason: "unsupported_run_state", schema: parsed.schema ?? null };
    }
    return { status: "ok", state: validateContract<WaygentRunStateV2>("waygent.run_state.v2", parsed) };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return { status: "missing", reason: "missing_run_state_v2" };
    }
    return {
      status: "invalid",
      reason: "invalid_run_state_v2",
      error: error instanceof Error ? error.message : String(error)
    };
  }
}
```

Use it in summary and detail:

```ts
function summarizeRealRun(runRoot: string, runId: string): RealRunSummary {
  const events = readEvents(runPaths(runRoot, runId).events);
  const readModel = projectRunReadModel({
    run_id: runId,
    events,
    state_result: readApiRunStateResult(runRoot, runId)
  });
  return {
    run_id: runId,
    status: readModel.status,
    trust_status: readModel.trust_status,
    apply_status: readModel.apply_status,
    total_events: readModel.total_events,
    last_event_type: readModel.last_event_type,
    run_read_model: readModel
  };
}
```

Add `run_read_model` and `state_error` to detail responses. `readRealRunDetail` should not override status after summary because the summary is already v2-first.

- [ ] Add API parity tests.

Create a real run root with trusted events and blocked v2 state, then assert `/runs` and `/runs/:id` match:

```ts
const list = await jsonFrom(handler(new Request("http://localhost/runs"), { runRoot: root }));
const detail = await jsonFrom(handler(new Request(`http://localhost/runs/${runId}`), { runRoot: root }));
expect(list.runs[0]).toMatchObject({
  run_id: runId,
  status: "blocked",
  apply_status: "blocked"
});
expect(detail).toMatchObject({
  run_id: runId,
  status: "blocked",
  apply_status: "blocked",
  run_read_model: { top_blocker: { failure_class: "needs_rebase" } }
});
```

- [ ] Update console real-run response types and model derivation.

In `apps/console/src/uiModel.ts`, add fields to `RealRunSummaryResponse` and `RealRunDetailResponse`:

```ts
run_read_model?: RunReadModelProjection | null;
state_error?: WaygentRunStateReadError | null;
```

Derive the header and next action from detail projections:

```ts
const nextAction = response.operational_maturity?.next_action
  ?? response.run_read_model?.top_blocker?.summary
  ?? null;
const applyReadiness = response.apply_readiness ?? response.run_read_model?.apply_readiness ?? null;
```

Keep apply buttons based only on `apply_readiness.status === "ready"` and combined patch/checkpoint data already returned by API.

- [ ] Add console tests for list/detail parity.

The test should provide a mocked response with `status: "blocked"`, `apply_status: "blocked"`, `run_read_model.top_blocker.failure_class: "needs_rebase"`, and provider noise counts. Assert:

- header status is `blocked`;
- `next_action` names the blocker or operational maturity action;
- `apply_readiness.status` remains `blocked`;
- no model path turns provider readiness `ready` into apply-ready.

```yaml
id: T5
title: Refine provider cost and startup-noise diagnostics
owner_boundary: packages/lens-projectors provider and runtime cost projections
files:
  - path: packages/lens-projectors/src/runtimeCost.ts
    mode: edit
  - path: packages/lens-projectors/src/providerReadiness.ts
    mode: edit
  - path: packages/lens-projectors/src/operationalMaturity.ts
    mode: edit
  - path: packages/lens-projectors/tests/operationalMaturity.test.ts
    mode: edit
  - path: packages/provider-adapters/tests/providerLogSummary.test.ts
    mode: edit
acceptance:
  - command: bun test packages/lens-projectors/tests/operationalMaturity.test.ts packages/provider-adapters/tests/providerLogSummary.test.ts
  - expected: successful providers with noisy stderr stay ready, while runtime/provider projections recommend startup-noise cleanup and provider-cost inspection
risks:
  - Startup noise must not hide true auth, command-not-found, timeout, or malformed-result failures. Preserve the existing failure checks before noisy-ready recommendations.
```

### T5 Steps

- [ ] Add a provider-noise helper in `providerReadiness.ts`.

Keep `looksAuthRequired`, `looksUnavailable`, timeout, exit code, and missing worker result checks before this helper:

```ts
function hasStartupNoise(summary: ProviderReadinessProjection["stderr_summary"]): boolean {
  if (!summary) return false;
  const plugin = summary.counts.plugin_manifest ?? 0;
  const skillLoader = summary.counts.skill_loader ?? 0;
  const warnings = summary.counts.warning ?? 0;
  return summary.total_lines >= 100 || plugin + skillLoader + warnings >= 25;
}
```

When the provider is successful but noisy, keep `status: "ready"`:

```ts
const stderrSummary = latestAttempt.process?.stderr_summary ?? null;
if (hasStartupNoise(stderrSummary)) {
  return projection(
    input.state.run_id,
    provider,
    "ready",
    command,
    stderrSummary,
    null,
    attemptRefs,
    `Provider ${provider} is ready, but startup stderr noise is high; clean plugin and skill-loader warnings before benchmarking provider cost.`
  );
}
return projection(input.state.run_id, provider, "ready", command, stderrSummary, null, attemptRefs, `Provider ${provider} has successful process evidence.`);
```

- [ ] Add provider-noise recommendations to `runtimeCost.ts`.

Pass the state into `runtimeRecommendations` or compute provider noise before calling it:

```ts
const providerNoise = providerNoiseSummary(input.state);
recommended_next_actions: runtimeRecommendations(
  explanation.recommended_next_actions,
  phaseTotals,
  input.dogfood_evidence,
  providerNoise
)
```

Add helper and recommendation:

```ts
function providerNoiseSummary(state: WaygentRunStateV2): { high: boolean; total_lines: number } {
  const latest = state.provider_attempts.at(-1);
  const summary = latest?.process?.stderr_summary;
  if (!summary) return { high: false, total_lines: 0 };
  const plugin = summary.counts.plugin_manifest ?? 0;
  const skillLoader = summary.counts.skill_loader ?? 0;
  const warnings = summary.counts.warning ?? 0;
  return {
    high: summary.total_lines >= 100 || plugin + skillLoader + warnings >= 25,
    total_lines: summary.total_lines
  };
}

if (providerNoise.high) {
  recommendations.add(`Clean provider startup stderr noise before benchmarking provider cost (${providerNoise.total_lines} stderr lines summarized).`);
}
```

- [ ] Add projection tests.

Extend `packages/lens-projectors/tests/operationalMaturity.test.ts` with a state that has:

- provider phase as the top hotspot;
- latest provider attempt exit code `0`;
- `worker_result_ref` present;
- `stderr_summary.total_lines: 2091`;
- `plugin_manifest` and `skill_loader` counts above the threshold.

Assert:

```ts
expect(maturity.provider_readiness).toMatchObject({
  status: "ready",
  recommended_next_action: expect.stringContaining("startup stderr noise")
});
expect(maturity.runtime_cost.recommended_next_actions.join("\n")).toContain("provider cost");
expect(maturity.runtime_cost.recommended_next_actions.join("\n")).toContain("startup stderr noise");
```

```yaml
id: T6
title: Add scenario coverage, docs, Graphify refresh, and final verification
owner_boundary: packages/testkit, integration tests, docs, Graphify output
files:
  - path: packages/testkit/src/waygentScenarioHarness.ts
    mode: edit
  - path: packages/testkit/tests/waygentScenarioHarness.test.ts
    mode: edit
  - path: tests/waygent-scenarios/checkpoint-dry-run-conflict.json
    mode: owned
  - path: tests/integration/waygent-scenarios.test.ts
    mode: edit
  - path: docs/operations/waygent.md
    mode: edit
  - path: docs/operations/verification.md
    mode: edit
  - path: docs/architecture/waygent.md
    mode: edit
  - path: graphify-out/GRAPH_REPORT.md
    mode: owned
  - path: graphify-out/graph.json
    mode: owned
acceptance:
  - command: bun run waygent:scenarios && bun run waygent:dogfood && git diff --check
  - expected: checkpoint dry-run conflict fixture replays as blocked with needs_rebase and docs/Graphify are clean
risks:
  - A scenario that mutates source during the run can be flaky. Prefer a deterministic harness fault that rewrites v2 state and replay normalization from recorded checkpoint dry-run evidence.
```

### T6 Steps

- [ ] Extend the scenario harness with a deterministic dry-run conflict fault.

Add a scenario flag while preserving existing flags:

```ts
export interface WaygentScenario {
  id: string;
  title: string;
  provider_fixture: WaygentScenarioProviderFixture;
  source_dirty_before_apply: boolean;
  force_missing_checkpoint: boolean;
  force_checkpoint_dry_run_conflict?: boolean;
  plan: string;
  expected: WaygentScenarioExpectedReplay;
}
```

Validate the optional flag as boolean when present:

```ts
if (raw.force_checkpoint_dry_run_conflict !== undefined && typeof raw.force_checkpoint_dry_run_conflict !== "boolean") {
  throw new Error(`${raw.id} must set force_checkpoint_dry_run_conflict to a boolean when present`);
}
```

Normalize blockers:

```ts
if (scenario.force_checkpoint_dry_run_conflict) blockers.push("checkpoint_dry_run_conflict");
```

Fault the returned state after a real fake-provider run:

```ts
if (scenario.force_checkpoint_dry_run_conflict) {
  for (const task of Object.values(next.tasks)) {
    task.status = "blocked";
    task.latest_failure_class = "needs_rebase";
    task.checkpoint_refs = [];
  }
  next.status = "blocked";
  next.lifecycle_outcome = "blocked";
  next.current_phase = "recover";
  next.apply = { status: "blocked", reason: "needs_rebase" };
  next.completion_audit = {
    ...(next.completion_audit ?? {}),
    status: "failed",
    reason: "needs_rebase"
  };
}
```

The runtime-level `checkpointArtifacts` test proves the real `git apply --check` conflict. The scenario fixture proves replay/read-surface behavior deterministically.

- [ ] Add `tests/waygent-scenarios/checkpoint-dry-run-conflict.json`.

```json
{
  "id": "checkpoint-dry-run-conflict",
  "title": "Checkpoint dry-run conflict blocks apply",
  "provider_fixture": "fake-success",
  "source_dirty_before_apply": false,
  "force_missing_checkpoint": false,
  "force_checkpoint_dry_run_conflict": true,
  "plan": "```yaml waygent-task\nid: task_checkpoint_conflict\ntitle: Checkpoint conflict task\ndependencies: []\nfile_claims:\n  - path: checkpoint-conflict.txt\n    mode: owned\nrisk: low\nverify:\n  - printf checkpoint-conflict\n```",
  "expected": {
    "run_status": "failed",
    "apply_status": "blocked",
    "event_types": [
      "platform.run_started",
      "runway.safe_wave_selected",
      "runway.worker_result",
      "runway.verification_result",
      "runway.checkpoint_created",
      "runway.apply_dry_run_result",
      "lens.trust_report_updated"
    ],
    "safe_wave": ["task_checkpoint_conflict"],
    "checkpoints": [],
    "blockers": ["checkpoint_dry_run_conflict"],
    "failure_classes": ["needs_rebase"]
  }
}
```

- [ ] Update docs.

`docs/operations/waygent.md` should state:

```md
### Checkpoint Dry-Run Conflicts

When a checkpoint manifest and patch exist but `git apply --check` fails against
the current source checkout, Waygent reports `needs_rebase` instead of
`missing_checkpoint`. Apply remains blocked. `waygent explain` points to the
dry-run evidence and failed files when available. `waygent resume` offers
checkpoint regeneration or a human decision, not apply.
```

`docs/operations/verification.md` should list the targeted test commands from this plan and the scenario/dogfood gates.

`docs/architecture/waygent.md` should mention that CLI, API, and console consume the shared run-read projector and prefer `waygent.run_state.v2` over event-derived status for current runs.

- [ ] Refresh Graphify after docs/code structure changes:

```bash
graphify update .
```

- [ ] Run final verification:

```bash
bun test packages/orchestrator/tests/checkpointArtifacts.test.ts packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/tests/runCommandsV2.test.ts
bun test packages/lens-projectors/tests/runReadModel.test.ts packages/lens-projectors/tests/operationalMaturity.test.ts packages/provider-adapters/tests/providerLogSummary.test.ts
bun test apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts packages/testkit/tests/waygentScenarioHarness.test.ts
bun run check
bun run waygent:scenarios
bun run waygent:dogfood
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

## Execution Order

Sequential shared-core tasks:

1. `T1` must land before any task-state or surface work.
2. `T2` must land after `T1` because task state depends on the dry-run failure class.
3. `T3` must land after `T2` because the shared read model needs the final blocker semantics.

Parallel-safe tasks after `T3`:

- `T4` API work and console model work can split if both consume `projectRunReadModel`.
- `T5` provider cost/noise projections can run in parallel with API/console work because it is read-only and shares only lens-projector tests.
- `T6` docs and scenario fixture should wait until the final field names from `T1` through `T5` are stable.

Human approval gates:

- The design is already approved.
- This plan is the next approval gate before implementation.
- Live provider smoke checks require an explicit opt-in and are not part of default verification.

## Verification

Targeted tests:

```bash
bun test packages/orchestrator/tests/checkpointArtifacts.test.ts packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/tests/runCommandsV2.test.ts
bun test packages/lens-projectors/tests/runReadModel.test.ts packages/lens-projectors/tests/operationalMaturity.test.ts packages/provider-adapters/tests/providerLogSummary.test.ts
bun test apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts packages/testkit/tests/waygentScenarioHarness.test.ts
```

Full offline checks:

```bash
bun run check
bun run waygent:scenarios
bun run waygent:dogfood
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

Optional live checks:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Run native kernel tests only if implementation touches `native/kernel`:

```bash
cd native/kernel && cargo test --workspace
```

## Review

Before reporting implementation complete:

- Read `code_review.md`.
- Confirm `needs_rebase` never enables apply readiness.
- Confirm `missing_checkpoint` is still reserved for absent or unresolvable checkpoint artifacts.
- Confirm invalid or unsupported v2 state blocks current-run readiness instead of silently trusting events.
- Confirm provider startup noise remains diagnostic and does not override kernel verification or apply readiness.
- Confirm Graphify was refreshed after code/docs structure changes.
