# Waygent Safe-Wave Parallel Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speed up Waygent without weakening apply-readiness trust by running scheduler-approved safe-wave tasks in parallel while serializing event and state writes.

**Architecture:** Phase 1 adds a single run writer, task execution results, bounded safe-wave parallelism, unique dry-run scratch files, provider replay fixtures, and timing evidence. Phase 2 reduces fixed runtime overhead through worktree and artifact-index infrastructure. Phase 3 exposes plan cost and dogfood evidence to operators through inspect/API/console and docs.

**Tech Stack:** Bun, TypeScript project references, filesystem JSON/JSONL artifacts, git worktrees, `@waygent/orchestrator`, `@waygent/runway-control`, `@waygent/provider-adapters`, `@waygent/lens-store`, `@waygent/lens-projectors`, React/Vite console.

---

## Source Design

- Design: `docs/architecture/2026-05-21-waygent-safe-wave-parallel-runtime-design.md`
- Architecture index: `docs/architecture/waygent.md`
- Current design commit: `b1aa805`
- Source audit basis in the design: `9928c2c`

## Non-Negotiable Boundaries

- Do not weaken verification, checkpoint validation, dry-run checks, completion audit, reconciliation, or apply readiness.
- Do not run tasks in parallel unless `computeSafeWave()` released them in the same safe wave.
- Do not let providers write AgentLens events or mutate the source checkout.
- Do not add active `kws-cpe.*`, `kws-cme.*`, or `kws.orchestrator.*` event namespaces.
- Do not route Waygent through `skills/kws-codex-plan-executor` or `skills/kws-claude-multi-agent-executor`.
- Keep live Codex and Claude smoke tests opt-in through `WAYGENT_LIVE_PROVIDER`.
- Keep runtime state, `.agentlens/`, `.claude/`, `.codex-orchestrator/`, `.orchestrator/`, `.superpowers/`, `node_modules/`, `.venv/`, build outputs, caches, and `.DS_Store` out of git.

## File Structure And Ownership

### Phase 1: Parallel Speed Path

```yaml
files:
  - path: packages/orchestrator/src/checkpointArtifacts.ts
    mode: edit
    responsibility: Replace fixed source-checkout dry-run patch path with unique scratch paths.
  - path: packages/orchestrator/tests/checkpointArtifacts.test.ts
    mode: edit
    responsibility: Prove concurrent checkpoint dry-runs do not collide and still update manifest evidence.
  - path: packages/orchestrator/src/runExecutionContext.ts
    mode: create
    responsibility: Own event sequence allocation, ordered event append, in-memory v2 state, serialized state mutation, and state flush.
  - path: packages/orchestrator/tests/runExecutionContext.test.ts
    mode: create
    responsibility: Prove event sequence ordering and state mutation serialization.
  - path: packages/orchestrator/src/taskExecutor.ts
    mode: create
    responsibility: Execute one task in an isolated worktree and return a task execution result without writing run-level truth.
  - path: packages/orchestrator/src/safeWaveExecutor.ts
    mode: create
    responsibility: Execute scheduler-approved safe waves with bounded concurrency and deterministic result replay.
  - path: packages/orchestrator/src/orchestrator.ts
    mode: edit
    responsibility: Use run execution context, task executor, and safe-wave executor from `runWaygent()`.
  - path: packages/orchestrator/tests/orchestratorParallel.test.ts
    mode: create
    responsibility: Prove independent low-risk tasks execute as one parallel safe wave while conflicting or high-risk tasks still serialize.
  - path: packages/provider-adapters/tests/fixtures/codex-jsonl-agent-message.jsonl
    mode: create
    responsibility: Sanitized replay fixture for Codex JSONL telemetry plus agent-message worker result.
  - path: packages/provider-adapters/tests/fixtures/claude-fenced-result.txt
    mode: create
    responsibility: Sanitized replay fixture for Claude fenced worker JSON.
  - path: packages/provider-adapters/tests/providerReplay.test.ts
    mode: create
    responsibility: Replay provider fixtures through the same normalization code used by live adapters.
```

### Phase 2: Fixed-Cost Reduction

```yaml
files:
  - path: packages/orchestrator/src/worktreeManager.ts
    mode: create
    responsibility: Centralize task worktree preparation, source-head capture, cleanup status, and setup timing.
  - path: packages/orchestrator/tests/worktreeManager.test.ts
    mode: create
    responsibility: Prove manifest shape, source-head capture, cleanup status, and setup timing.
  - path: packages/lens-store/src/artifactIndex.ts
    mode: create
    responsibility: Record artifact refs, media type, sha256, byte length, producer phase, task id, and timestamps.
  - path: packages/lens-store/src/index.ts
    mode: edit
    responsibility: Export artifact-index helpers.
  - path: packages/lens-store/tests/artifactIndex.test.ts
    mode: create
    responsibility: Prove artifact index append, read, and ref lookup behavior.
  - path: packages/orchestrator/src/stateReconciliation.ts
    mode: edit
    responsibility: Use the artifact index as a fast existence map while preserving digest verification for critical artifacts.
  - path: packages/orchestrator/tests/stateReconciliation.test.ts
    mode: edit
    responsibility: Prove indexed reconciliation still catches missing artifacts and digest drift.
```

### Phase 3: Operator Feedback Loop

```yaml
files:
  - path: packages/lens-projectors/src/runtimeCost.ts
    mode: create
    responsibility: Project estimated waves, withheld reasons, measured task timings, wave timings, and dogfood evidence.
  - path: packages/lens-projectors/src/index.ts
    mode: edit
    responsibility: Export runtime cost projection.
  - path: packages/lens-projectors/tests/runtimeCost.test.ts
    mode: create
    responsibility: Prove wave estimates, serial barriers, and measured durations are projected from state.
  - path: packages/orchestrator/src/runCommands.ts
    mode: edit
    responsibility: Include runtime cost and dogfood evidence in inspect output.
  - path: apps/api/src/server.ts
    mode: edit
    responsibility: Include runtime cost projection in real run detail.
  - path: apps/api/tests/api.test.ts
    mode: edit
    responsibility: Assert runtime cost appears in run detail without changing readiness behavior.
  - path: apps/console/src/uiModel.ts
    mode: edit
    responsibility: Map waves, serial barriers, measured durations, and dogfood evidence into console UI model.
  - path: apps/console/src/App.tsx
    mode: edit
    responsibility: Render runtime cost and dogfood evidence as read-only inspection data.
  - path: apps/console/src/uiModel.test.ts
    mode: edit
    responsibility: Assert runtime cost and dogfood fields render for ready and blocked runs.
  - path: docs/operations/waygent.md
    mode: edit
    responsibility: Document how to write faster safe-wave-friendly plans and how to read dogfood evidence.
```

## Execution Order

Sequential Phase 1 tasks:

1. Task 1 unique dry-run scratch.
2. Task 2 single event/state writer.
3. Task 3 task execution result extraction.
4. Task 4 bounded safe-wave parallel executor.
5. Task 5 provider contract replay fixtures.
6. Task 6 Phase 1 verification and docs notes.

Sequential Phase 2 tasks after Phase 1 is complete:

7. Task 7 worktree manager.
8. Task 8 artifact index.
9. Task 9 index-assisted reconciliation.

Sequential Phase 3 tasks after Phase 2 is complete:

10. Task 10 runtime cost projection.
11. Task 11 inspect/API/console exposure.
12. Task 12 operations docs and final verification.

Human approval gates:

- Review after Task 4 before changing provider replay coverage.
- Review after Task 6 before starting Phase 2.
- Review after Task 9 before starting Phase 3.
- Review after Task 12 before broad merge, push, or PR.

---

## Phase 1: Parallel Speed Path

### Task 1: Make Checkpoint Dry-Run Scratch Paths Parallel-Safe

**Files:**
- Modify: `packages/orchestrator/src/checkpointArtifacts.ts`
- Modify: `packages/orchestrator/tests/checkpointArtifacts.test.ts`

- [ ] **Step 1: Write failing concurrent dry-run test**

Add this test to `packages/orchestrator/tests/checkpointArtifacts.test.ts`:

```ts
test("checkpoint dry-runs use unique scratch files and can run concurrently", async () => {
  const fixture = createCheckpointFixture("waygent-parallel-dry-run-");
  const first = createCheckpointArtifact({
    run_root: fixture.runRoot,
    run_id: "run_parallel_dry_run",
    task_id: "task_a",
    candidate_id: "candidate_a",
    worktree_path: fixture.worktreeA,
    changed_files: ["a.txt"],
    verification_refs: []
  });
  const second = createCheckpointArtifact({
    run_root: fixture.runRoot,
    run_id: "run_parallel_dry_run",
    task_id: "task_b",
    candidate_id: "candidate_b",
    worktree_path: fixture.worktreeB,
    changed_files: ["b.txt"],
    verification_refs: []
  });

  const [firstDryRun, secondDryRun] = await Promise.all([
    Promise.resolve(dryRunCheckpointPatch({
      run_root: fixture.runRoot,
      checkpoint_ref: first.manifest_ref,
      source: fixture.source
    })),
    Promise.resolve(dryRunCheckpointPatch({
      run_root: fixture.runRoot,
      checkpoint_ref: second.manifest_ref,
      source: fixture.source
    }))
  ]);

  expect(firstDryRun.status).toBe("passed");
  expect(secondDryRun.status).toBe("passed");
  expect(firstDryRun.evidence_ref).not.toBe(secondDryRun.evidence_ref);
  expect(existsSync(join(fixture.source, ".waygent-dry-run.patch"))).toBe(false);
});
```

Add this helper in the same test file when no equivalent helper is already present:

```ts
function createCheckpointFixture(prefix: string) {
  const source = mkdtempSync(join(tmpdir(), `${prefix}source-`));
  initGit(source);
  const runRoot = mkdtempSync(join(tmpdir(), `${prefix}run-`));
  const worktreeA = cloneWorktree(source, `${prefix}a-`);
  const worktreeB = cloneWorktree(source, `${prefix}b-`);
  writeFileSync(join(worktreeA, "a.txt"), "a\n");
  writeFileSync(join(worktreeB, "b.txt"), "b\n");
  return { source, runRoot, worktreeA, worktreeB };
}

function initGit(path: string): void {
  for (const args of [
    ["init", "-q"],
    ["config", "user.email", "test@example.com"],
    ["config", "user.name", "Waygent"],
    ["commit", "--allow-empty", "-q", "-m", "base"]
  ]) {
    const result = Bun.spawnSync(["git", ...args], { cwd: path });
    if (result.exitCode !== 0) throw new Error(`git ${args.join(" ")} failed`);
  }
}

function cloneWorktree(source: string, prefix: string): string {
  const target = mkdtempSync(join(tmpdir(), prefix));
  rmSync(target, { recursive: true, force: true });
  const result = Bun.spawnSync(["git", "clone", "--quiet", source, target]);
  if (result.exitCode !== 0) throw new Error("git clone failed");
  return target;
}
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
bun test packages/orchestrator/tests/checkpointArtifacts.test.ts
```

Expected: FAIL because `dryRunCheckpointPatch()` still writes `.waygent-dry-run.patch` in the source checkout.

- [ ] **Step 3: Implement unique scratch paths**

In `packages/orchestrator/src/checkpointArtifacts.ts`, replace the fixed dry-run patch path with a temporary file:

```ts
const scratchDir = mkdtempSync(join(tmpdir(), "waygent-checkpoint-dry-run-"));
const patchPath = join(scratchDir, "candidate.patch");
try {
  writeFileSync(patchPath, resolved.patch);
  const dryRun = spawnSync("git", ["apply", "--check", patchPath], {
    cwd: input.source,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  const status = dryRun.status === 0 ? "passed" : "failed";
  const evidence = writeCheckpointDryRunEvidence(input.run_root, input.checkpoint_ref, {
    status,
    stdout: dryRun.stdout,
    stderr: dryRun.stderr
  });
  updateCheckpointManifestDryRun(input.run_root, input.checkpoint_ref, status, evidence);
  return {
    status,
    ...(status === "failed" ? { reason: "patch_dry_run_failed" as const } : {}),
    evidence_ref: evidence
  };
} finally {
  rmSync(scratchDir, { recursive: true, force: true });
}
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
bun test packages/orchestrator/tests/checkpointArtifacts.test.ts \
  packages/orchestrator/tests/orchestratorApplyE2E.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/orchestrator/src/checkpointArtifacts.ts \
  packages/orchestrator/tests/checkpointArtifacts.test.ts
git commit -m "fix: isolate Waygent checkpoint dry-run scratch"
```

### Task 2: Add The Single Event/State Writer

**Files:**
- Create: `packages/orchestrator/src/runExecutionContext.ts`
- Create: `packages/orchestrator/tests/runExecutionContext.test.ts`
- Modify: `packages/orchestrator/src/index.ts`

- [ ] **Step 1: Write failing context tests**

Create `packages/orchestrator/tests/runExecutionContext.test.ts`:

```ts
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readEvents, runPaths } from "@waygent/lens-store";
import { buildRunEvent } from "../src/runEvents";
import { createRunExecutionContext } from "../src/runExecutionContext";
import { baseV2State } from "./support/runStateFixture";

describe("RunExecutionContext", () => {
  test("serializes event sequence allocation and state mutation", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-context-"));
    const state = baseV2State({ root, run_id: "run_context" });
    const context = createRunExecutionContext({ root, state, next_sequence: 1 });

    context.emit((sequence) => buildRunEvent({
      run_id: "run_context",
      sequence,
      event_type: "platform.run_started",
      phase: "platform",
      outcome: "running",
      summary: "started",
      payload: {}
    }));
    context.mutateState((draft) => {
      draft.current_phase = "dispatch";
      draft.tasks.task_a!.status = "running";
    });
    context.emit((sequence) => buildRunEvent({
      run_id: "run_context",
      sequence,
      event_type: "runway.worker_result",
      phase: "worker",
      outcome: "success",
      summary: "worker",
      payload: {}
    }));
    context.flushState();

    expect(readEvents(runPaths(root, "run_context").events).map((event) => event.sequence)).toEqual([1, 2]);
    expect(context.state.tasks.task_a?.status).toBe("running");
  });
});
```

Create `packages/orchestrator/tests/support/runStateFixture.ts` with a minimal valid `WaygentRunStateV2` fixture:

```ts
import { join } from "node:path";
import type { WaygentRunStateV2 } from "@waygent/contracts";

export function baseV2State(input: { root: string; run_id: string }): WaygentRunStateV2 {
  const runRoot = join(input.root, input.run_id);
  return {
    schema: "waygent.run_state.v2",
    run_id: input.run_id,
    workspace: input.root,
    source_branch: null,
    worktree_root: join(input.root, "worktrees"),
    run_root: runRoot,
    artifact_root: join(runRoot, "artifacts"),
    state_path: join(runRoot, "state.json"),
    event_journal_path: join(runRoot, "events.jsonl"),
    plan_path: null,
    spec_path: null,
    provider_profile: { provider: "fake" },
    status: "running",
    lifecycle_outcome: null,
    current_phase: "preflight",
    preflight: null,
    worktrees: [],
    tasks: {
      task_a: {
        id: "task_a",
        status: "ready",
        risk: "low",
        dependencies: [],
        file_claims: [{ path: "a.txt", mode: "owned" }],
        attempts: [],
        task_packet_path: null,
        task_packet_sha256: null,
        unit_manifest: { allowed_write_globs: ["a.txt"], forbidden_write_globs: [".git/**"] },
        checkpoint_refs: [],
        latest_failure_class: null,
        decision_packet_ref: null,
        timing: {}
      }
    },
    safe_waves: [{ wave_id: "wave_1", ready: ["task_a"], withheld: [] }],
    provider_attempts: [],
    reviews: [],
    verification: [],
    recovery: [],
    apply: { status: "not_applied" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: null,
    timestamps: { started_at: "2026-05-21T00:00:00.000Z", updated_at: "2026-05-21T00:00:00.000Z", completed_at: null }
  };
}
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
bun test packages/orchestrator/tests/runExecutionContext.test.ts
```

Expected: FAIL because `runExecutionContext.ts` is not implemented yet.

- [ ] **Step 3: Implement the context**

Create `packages/orchestrator/src/runExecutionContext.ts`:

```ts
import type { AgentLensEvent, WaygentRunStateV2 } from "@waygent/contracts";
import { appendEvent, runPaths } from "@waygent/lens-store";
import { writeRunStateV2 } from "./runState";

export interface RunExecutionContextInput {
  root: string;
  state: WaygentRunStateV2;
  next_sequence: number;
}

export interface RunExecutionContext {
  readonly root: string;
  readonly run_id: string;
  readonly state: WaygentRunStateV2;
  emit(build: (sequence: number) => AgentLensEvent): AgentLensEvent;
  mutateState(mutator: (state: WaygentRunStateV2) => void): void;
  flushState(): void;
  nextSequence(): number;
}

export function createRunExecutionContext(input: RunExecutionContextInput): RunExecutionContext {
  let sequence = input.next_sequence;
  const state = input.state;
  const eventsPath = runPaths(input.root, state.run_id).events;

  return {
    root: input.root,
    run_id: state.run_id,
    state,
    nextSequence() {
      const value = sequence;
      sequence += 1;
      return value;
    },
    emit(build) {
      const event = build(this.nextSequence());
      appendEvent(eventsPath, event);
      return event;
    },
    mutateState(mutator) {
      mutator(state);
      state.timestamps.updated_at = new Date().toISOString();
    },
    flushState() {
      writeRunStateV2(input.root, state);
    }
  };
}
```

Export it from `packages/orchestrator/src/index.ts` if package consumers need it in tests:

```ts
export * from "./runExecutionContext";
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
bun test packages/orchestrator/tests/runExecutionContext.test.ts \
  packages/orchestrator/tests/runStateV2.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/orchestrator/src/runExecutionContext.ts \
  packages/orchestrator/src/index.ts \
  packages/orchestrator/tests/runExecutionContext.test.ts \
  packages/orchestrator/tests/support/runStateFixture.ts
git commit -m "feat: add Waygent run execution context"
```

### Task 3: Extract Task Execution Results

**Files:**
- Create: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Create: `packages/orchestrator/tests/taskExecutor.test.ts`

- [ ] **Step 1: Write failing task executor test**

Create `packages/orchestrator/tests/taskExecutor.test.ts`:

```ts
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { executeWaygentTask } from "../src/taskExecutor";
import { initSourceCheckout, oneTaskPlan } from "./support/orchestratorFixtures";

describe("executeWaygentTask", () => {
  test("returns task evidence without appending run events or flushing state", async () => {
    const workspace = initSourceCheckout("waygent-task-executor-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-task-executor-root-"));
    const result = await executeWaygentTask({
      root,
      run_id: "run_task_executor",
      workspace,
      worktree_root: join(root, "worktrees"),
      task: oneTaskPlan("task_a", "a.txt"),
      dependencies: [],
      provider_profile: { provider: "fake", execution_mode: "multi-agent" },
      provider_processes: {}
    });

    expect(result.task_id).toBe("task_a");
    expect(result.status).toBe("verified");
    expect(result.provider_attempt).toMatchObject({ task_id: "task_a", provider: "fake" });
    expect(result.verification_records.length).toBeGreaterThan(0);
    expect(result.checkpoint_refs[0]).toContain("artifacts/checkpoints/task_a/");
    expect(result.events.map((event) => event.event_type)).toContain("runway.worker_result");
  });
});
```

Create `packages/orchestrator/tests/support/orchestratorFixtures.ts` with shared helpers:

```ts
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export function initSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  writeFileSync(join(workspace, "README.md"), "fixture\n");
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

export function oneTaskPlan(taskId: string, path: string): string {
  return [
    "```yaml waygent-task",
    `id: ${taskId}`,
    `title: Create ${path}`,
    "dependencies: []",
    "file_claims:",
    `  - path: ${path}`,
    "    mode: owned",
    "risk: low",
    "verify:",
    `  - test -f ${path}`,
    "```"
  ].join("\n");
}
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
bun test packages/orchestrator/tests/taskExecutor.test.ts
```

Expected: FAIL because `taskExecutor.ts` is not implemented yet.

- [ ] **Step 3: Move task-local logic into `executeWaygentTask()`**

Create `packages/orchestrator/src/taskExecutor.ts` with these exported types:

```ts
export interface WaygentTaskExecutionResult {
  task_id: string;
  status: "verified" | "blocked";
  latest_failure_class: FailureClass | null;
  worktree_manifest: WorktreeManifest;
  task_packet_path: string;
  task_packet_sha256: string;
  provider_attempt: ProviderAttempt;
  verification_records: Array<Record<string, unknown>>;
  checkpoint_refs: string[];
  events: Array<Omit<AgentLensEvent, "sequence">>;
  timing: { started: string; completed: string; duration_ms: number };
}
```

Move the task-local work from `runOneTask()` in `orchestrator.ts` into `executeWaygentTask()`:

- `planWorktree()` and `buildWorktreeManifest()`;
- `prepareTaskWorktree()`;
- task packet creation;
- provider prompt and adapter execution;
- provider artifact writes;
- fake provider materialization;
- kernel verification;
- diff-scope validation;
- checkpoint creation and dry-run;
- task-local event intent creation.

Keep run-level state mutation, event sequence assignment, safe-wave recompute, completion audit, and reconciliation in `orchestrator.ts`.

- [ ] **Step 4: Keep existing run behavior green**

Run:

```bash
bun test packages/orchestrator/tests/taskExecutor.test.ts \
  packages/orchestrator/tests/orchestratorRunV2.test.ts \
  packages/orchestrator/tests/orchestratorApplyE2E.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/orchestrator/src/taskExecutor.ts \
  packages/orchestrator/src/orchestrator.ts \
  packages/orchestrator/src/index.ts \
  packages/orchestrator/tests/taskExecutor.test.ts \
  packages/orchestrator/tests/support/orchestratorFixtures.ts
git commit -m "refactor: return Waygent task execution evidence"
```

### Task 4: Add Bounded Safe-Wave Parallel Execution

**Files:**
- Create: `packages/orchestrator/src/safeWaveExecutor.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Create: `packages/orchestrator/tests/orchestratorParallel.test.ts`

- [ ] **Step 1: Write failing parallelism tests**

Create `packages/orchestrator/tests/orchestratorParallel.test.ts`:

```ts
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readEvents } from "@waygent/lens-store";
import { runWaygent } from "../src/orchestrator";
import { readRunStateV2 } from "../src/runState";
import { initSourceCheckout } from "./support/orchestratorFixtures";

describe("Waygent safe-wave parallel execution", () => {
  test("executes independent low-risk tasks in one bounded parallel wave", async () => {
    const workspace = initSourceCheckout("waygent-parallel-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-parallel-root-"));
    const startedAt = performance.now();

    await runWaygent({
      root,
      workspace,
      run_id: "run_parallel",
      plan: independentPlan(4),
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const elapsed = performance.now() - startedAt;
    const state = readRunStateV2(root, "run_parallel");
    const events = readEvents(join(root, "run_parallel", "events.jsonl"));

    expect(state.safe_waves[0]?.ready).toEqual(["task_1", "task_2", "task_3", "task_4"]);
    expect(Object.values(state.tasks).every((task) => task.status === "verified")).toBe(true);
    expect(state.provider_attempts).toHaveLength(4);
    expect(new Set(events.map((event) => event.sequence)).size).toBe(events.length);
    expect(state.completion_audit).toMatchObject({ status: "passed" });
    expect(elapsed).toBeLessThan(900);
  });

  test("keeps conflicting claims serialized by the scheduler", async () => {
    const workspace = initSourceCheckout("waygent-serial-claim-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-serial-claim-root-"));

    await runWaygent({
      root,
      workspace,
      run_id: "run_serial_claim",
      plan: conflictingPlan(),
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_serial_claim");
    expect(state.safe_waves[0]?.ready).toEqual(["task_first"]);
    expect(state.safe_waves[1]?.ready).toEqual(["task_second"]);
    expect(readFileSync(join(workspace, "README.md"), "utf8")).toBe("fixture\n");
  });
});
```

Use plan helpers that create four independent `owned` files for `independentPlan(4)` and two tasks touching `README.md` for `conflictingPlan()`.
Use these helpers in `orchestratorParallel.test.ts`:

```ts
function independentPlan(count: number): string {
  return Array.from({ length: count }, (_, index) => {
    const id = `task_${index + 1}`;
    const path = `file-${index + 1}.txt`;
    return [
      "```yaml waygent-task",
      `id: ${id}`,
      `title: Create ${path}`,
      "dependencies: []",
      "file_claims:",
      `  - path: ${path}`,
      "    mode: owned",
      "risk: low",
      "verify:",
      `  - test -f ${path}`,
      "```"
    ].join("\n");
  }).join("\n");
}

function conflictingPlan(): string {
  return [
    "```yaml waygent-task",
    "id: task_first",
    "title: First README update",
    "dependencies: []",
    "file_claims:",
    "  - path: README.md",
    "    mode: owned",
    "risk: low",
    "verify:",
    "  - test -f README.md",
    "```",
    "```yaml waygent-task",
    "id: task_second",
    "title: Second README update",
    "dependencies: []",
    "file_claims:",
    "  - path: README.md",
    "    mode: owned",
    "risk: low",
    "verify:",
    "  - test -f README.md",
    "```"
  ].join("\n");
}
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorParallel.test.ts
```

Expected: FAIL because the runtime still executes safe-wave tasks serially and does not record wave timing.

- [ ] **Step 3: Implement bounded concurrency helper**

Create `packages/orchestrator/src/safeWaveExecutor.ts`:

```ts
export interface SafeWaveExecutorInput<T> {
  task_ids: string[];
  concurrency: number;
  execute: (taskId: string) => Promise<T>;
}

export async function executeBoundedSafeWave<T>(input: SafeWaveExecutorInput<T>): Promise<Array<{ task_id: string; result: T }>> {
  const concurrency = Math.max(1, Math.min(input.concurrency, input.task_ids.length || 1));
  const results: Array<{ task_id: string; result: T }> = [];
  let nextIndex = 0;

  async function worker(): Promise<void> {
    while (nextIndex < input.task_ids.length) {
      const index = nextIndex;
      nextIndex += 1;
      const taskId = input.task_ids[index]!;
      results[index] = { task_id: taskId, result: await input.execute(taskId) };
    }
  }

  await Promise.all(Array.from({ length: concurrency }, () => worker()));
  return results;
}

export function resolveWaveConcurrency(input: { provider: string; safe_wave_size: number; env?: NodeJS.ProcessEnv }): number {
  const configured = Number(input.env?.WAYGENT_WAVE_CONCURRENCY);
  if (Number.isFinite(configured) && configured > 0) {
    return Math.max(1, Math.min(Math.floor(configured), input.safe_wave_size || 1));
  }
  if (input.provider === "fake") return Math.max(1, input.safe_wave_size);
  return Math.max(1, Math.min(2, input.safe_wave_size || 1));
}
```

- [ ] **Step 4: Wire safe-wave execution into `runWaygent()`**

In `packages/orchestrator/src/orchestrator.ts`:

- create `RunExecutionContext` after initial state construction;
- replace direct `appendEvent()` calls after initialization with `context.emit()`;
- replace `updateRunStateV2()` calls inside task execution with result replay through `context.mutateState()`;
- replace the inner `for (const taskId of activeSafeWave) await runOneTask(taskId)` loop with:

```ts
const waveStarted = performance.now();
const results = await executeBoundedSafeWave({
  task_ids: activeSafeWave,
  concurrency: resolveWaveConcurrency({
    provider: profile.provider,
    safe_wave_size: activeSafeWave.length,
    env: process.env
  }),
  execute: (taskId) => executeWaygentTask(taskExecutionInput(taskId))
});
for (const { result } of results) {
  replayTaskExecutionResult(context, result);
}
recordWaveTiming(context, {
  wave_id: `wave_${waveIndex}`,
  duration_ms: Math.round(performance.now() - waveStarted),
  task_ids: activeSafeWave
});
context.flushState();
```

Keep combined apply evidence, completion audit, trust report, and reconciliation after all waves finish.

- [ ] **Step 5: Run focused tests**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorParallel.test.ts \
  packages/orchestrator/tests/orchestratorRunV2.test.ts \
  packages/orchestrator/tests/orchestratorApplyE2E.test.ts \
  packages/orchestrator/tests/diffScope.test.ts \
  packages/orchestrator/tests/stateReconciliation.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator/src/safeWaveExecutor.ts \
  packages/orchestrator/src/orchestrator.ts \
  packages/orchestrator/src/index.ts \
  packages/orchestrator/tests/orchestratorParallel.test.ts
git commit -m "feat: execute Waygent safe waves in parallel"
```

### Task 5: Add Provider Contract Replay Fixtures

**Files:**
- Create: `packages/provider-adapters/tests/fixtures/codex-jsonl-agent-message.jsonl`
- Create: `packages/provider-adapters/tests/fixtures/claude-fenced-result.txt`
- Create: `packages/provider-adapters/tests/providerReplay.test.ts`
- Modify: `packages/provider-adapters/tests/codexAdapter.test.ts`
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts`

- [ ] **Step 1: Add replay fixtures**

Create `packages/provider-adapters/tests/fixtures/codex-jsonl-agent-message.jsonl`:

```jsonl
{"type":"thread.started","thread_id":"thread_fixture"}
{"type":"item.completed","item":{"type":"agent_message","text":"{\"schema\":\"runway.worker_result.v1\",\"task_id\":\"task_fixture\",\"candidate_id\":\"candidate_fixture\",\"status\":\"success\",\"summary\":\"fixture edit complete\",\"changed_files\":[\"fixture.txt\"],\"evidence\":{\"command\":\"codex\"}}"}}
{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}
```

Create `packages/provider-adapters/tests/fixtures/claude-fenced-result.txt`:

````text
Claude result:

```json
{"schema":"runway.worker_result.v1","task_id":"task_fixture","candidate_id":"candidate_fixture","status":"completed","summary":"fixture edit complete","changed_files":["fixture.txt"],"evidence":{"command":"claude"}}
```
````

- [ ] **Step 2: Write replay tests**

Create `packages/provider-adapters/tests/providerReplay.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { normalizeProcessOutput } from "../src";

const fixtures = join(import.meta.dir, "fixtures");

describe("provider contract replay fixtures", () => {
  test("replays Codex JSONL agent-message output", () => {
    const stdout = readFileSync(join(fixtures, "codex-jsonl-agent-message.jsonl"), "utf8");
    const result = normalizeProcessOutput("codex", "task_fixture", "candidate_fixture", {
      exitCode: 0,
      stdout,
      stderr: ""
    });

    expect(result.worker).toMatchObject({
      task_id: "task_fixture",
      candidate_id: "candidate_fixture",
      status: "completed",
      changed_files: ["fixture.txt"]
    });
    expect(result.process.stdout).toContain("turn.completed");
  });

  test("replays Claude fenced worker output", () => {
    const stdout = readFileSync(join(fixtures, "claude-fenced-result.txt"), "utf8");
    const result = normalizeProcessOutput("claude", "task_fixture", "candidate_fixture", {
      exitCode: 0,
      stdout,
      stderr: ""
    });

    expect(result.worker).toMatchObject({
      task_id: "task_fixture",
      candidate_id: "candidate_fixture",
      status: "completed",
      changed_files: ["fixture.txt"]
    });
  });
});
```

- [ ] **Step 3: Run replay tests**

Run:

```bash
bun test packages/provider-adapters/tests/providerReplay.test.ts \
  packages/provider-adapters/tests/codexAdapter.test.ts \
  packages/provider-adapters/tests/claudeAdapter.test.ts
```

Expected: PASS. If this fails, fix `normalizeProcessOutput()` without weakening malformed-output rejection.

- [ ] **Step 4: Commit**

```bash
git add packages/provider-adapters/tests/fixtures \
  packages/provider-adapters/tests/providerReplay.test.ts \
  packages/provider-adapters/tests/codexAdapter.test.ts \
  packages/provider-adapters/tests/claudeAdapter.test.ts \
  packages/provider-adapters/src/processAdapters.ts
git commit -m "test: replay Waygent provider process contracts"
```

### Task 6: Close Phase 1 With Verification And Docs Notes

**Files:**
- Modify: `docs/architecture/2026-05-21-waygent-safe-wave-parallel-runtime-design.md`
- Modify: `docs/operations/waygent.md`
- Modify: `package.json` if a focused Phase 1 script is useful.

- [ ] **Step 1: Add a Phase 1 status note**

Append a short implementation status block to `docs/architecture/2026-05-21-waygent-safe-wave-parallel-runtime-design.md`:

```md
## Implementation Status

Phase 1 is implemented when the following commits are present:

- unique checkpoint dry-run scratch paths;
- single run event/state writer;
- task execution result extraction;
- bounded safe-wave parallel executor;
- provider contract replay fixtures.

Phase 2 and Phase 3 remain planned follow-up work until their tasks are explicitly started.
```

- [ ] **Step 2: Document the operator behavior**

In `docs/operations/waygent.md`, add a section:

```md
## Safe-Wave Parallel Execution

Waygent may run tasks in the same scheduler-approved safe wave concurrently.
Parallelism never bypasses file-claim, dependency, risk, verification,
checkpoint, completion-audit, reconciliation, or apply-readiness gates.

Live providers default to conservative bounded concurrency. Set
`WAYGENT_WAVE_CONCURRENCY=<n>` only when the local machine and provider account
can sustain the requested parallel work.
```

- [ ] **Step 3: Run Phase 1 verification**

Run:

```bash
bun test packages/orchestrator/tests/checkpointArtifacts.test.ts \
  packages/orchestrator/tests/runExecutionContext.test.ts \
  packages/orchestrator/tests/taskExecutor.test.ts \
  packages/orchestrator/tests/orchestratorParallel.test.ts \
  packages/provider-adapters/tests/providerReplay.test.ts

bun run check
bun run platform:demo
bun run waygent:scenarios
git diff --check
```

Expected:

- all Bun test commands PASS;
- `platform:demo` prints a trusted run;
- `waygent:scenarios` passes all scenario fixtures;
- `git diff --check` prints no output.

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/2026-05-21-waygent-safe-wave-parallel-runtime-design.md \
  docs/operations/waygent.md \
  package.json
git commit -m "docs: record Waygent parallel runtime phase 1"
```

---

## Phase 2: Fixed-Cost Reduction

### Task 7: Introduce Worktree Manager

**Files:**
- Create: `packages/orchestrator/src/worktreeManager.ts`
- Create: `packages/orchestrator/tests/worktreeManager.test.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`

- [ ] **Step 1: Write worktree manager tests**

Create tests that assert:

```ts
expect(manifest).toMatchObject({
  task_id: "task_a",
  source: workspace,
  source_commit: expect.stringMatching(/[0-9a-f]{40}/),
  cleanup_status: "active"
});
expect(result.timing.duration_ms).toBeGreaterThanOrEqual(0);
```

Run:

```bash
bun test packages/orchestrator/tests/worktreeManager.test.ts
```

Expected: FAIL because `worktreeManager.ts` is not implemented yet.

- [ ] **Step 2: Implement `prepareManagedWorktree()`**

Create a manager that wraps the existing clone/reset behavior and returns:

```ts
export interface ManagedWorktree {
  manifest: WorktreeManifest;
  timing: { started: string; completed: string; duration_ms: number };
}
```

Use it from `taskExecutor.ts` instead of direct worktree preparation.

- [ ] **Step 3: Verify and commit**

Run:

```bash
bun test packages/orchestrator/tests/worktreeManager.test.ts \
  packages/orchestrator/tests/taskExecutor.test.ts \
  packages/orchestrator/tests/orchestratorParallel.test.ts
```

Expected: PASS.

Commit:

```bash
git add packages/orchestrator/src/worktreeManager.ts \
  packages/orchestrator/src/taskExecutor.ts \
  packages/orchestrator/tests/worktreeManager.test.ts
git commit -m "feat: manage Waygent task worktrees"
```

### Task 8: Add Artifact Index

**Files:**
- Create: `packages/lens-store/src/artifactIndex.ts`
- Modify: `packages/lens-store/src/index.ts`
- Create: `packages/lens-store/tests/artifactIndex.test.ts`
- Modify: `packages/orchestrator/src/runExecutionContext.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`

- [ ] **Step 1: Write artifact index tests**

Create `packages/lens-store/tests/artifactIndex.test.ts` with append/read/ref lookup assertions:

```ts
const entry = appendArtifactIndexEntry(root, {
  ref: "artifacts/worker/task_a.json",
  media_type: "application/json",
  sha256: "a".repeat(64),
  byte_length: 12,
  producer_phase: "worker",
  task_id: "task_a"
});
expect(readArtifactIndex(root)).toEqual([entry]);
expect(findArtifactIndexEntry(root, "artifacts/worker/task_a.json")).toMatchObject({
  producer_phase: "worker",
  task_id: "task_a"
});
```

- [ ] **Step 2: Implement artifact index helpers**

Create append/read/find helpers backed by `artifact-index.jsonl` in the run root. Keep the index append-only and validate sha length, byte length, and non-empty ref.

- [ ] **Step 3: Record entries from runtime writes**

When task packet, provider, worker, kernel, checkpoint, and dry-run artifacts are written, append matching index entries with producer phase and task id.

- [ ] **Step 4: Verify and commit**

Run:

```bash
bun test packages/lens-store/tests/artifactIndex.test.ts \
  packages/orchestrator/tests/taskExecutor.test.ts \
  packages/orchestrator/tests/orchestratorParallel.test.ts
```

Expected: PASS.

Commit:

```bash
git add packages/lens-store/src/artifactIndex.ts \
  packages/lens-store/src/index.ts \
  packages/lens-store/tests/artifactIndex.test.ts \
  packages/orchestrator/src/runExecutionContext.ts \
  packages/orchestrator/src/taskExecutor.ts
git commit -m "feat: index Waygent run artifacts"
```

### Task 9: Make Reconciliation Index-Assisted

**Files:**
- Modify: `packages/orchestrator/src/stateReconciliation.ts`
- Modify: `packages/orchestrator/tests/stateReconciliation.test.ts`

- [ ] **Step 1: Add reconciliation tests using the artifact index**

Extend `stateReconciliation.test.ts` with:

```ts
test("uses artifact index but still catches digest drift", () => {
  const fixture = writeReconciliationFixture("run_indexed_reconcile");
  corruptCombinedPatchBytes(fixture);

  const report = reconcileRunState(fixture.root, fixture.runId);

  expect(report.passed).toBe(false);
  expect(report.records).toEqual(expect.arrayContaining([
    expect.objectContaining({ failure_class: "state_drift" })
  ]));
});
```

- [ ] **Step 2: Use index as existence map**

In `stateReconciliation.ts`, load the index once at the start. Use it to check whether expected artifact refs were produced. Keep byte reads for task packet digest, checkpoint patch digest, combined patch digest, and event journal readability.

- [ ] **Step 3: Verify and commit**

Run:

```bash
bun test packages/orchestrator/tests/stateReconciliation.test.ts \
  packages/orchestrator/tests/runCommandsV2.test.ts \
  packages/orchestrator/tests/orchestratorParallel.test.ts
```

Expected: PASS.

Commit:

```bash
git add packages/orchestrator/src/stateReconciliation.ts \
  packages/orchestrator/tests/stateReconciliation.test.ts
git commit -m "feat: reconcile Waygent state with artifact index"
```

---

## Phase 3: Operator Feedback Loop

### Task 10: Add Runtime Cost Projection

**Files:**
- Create: `packages/lens-projectors/src/runtimeCost.ts`
- Modify: `packages/lens-projectors/src/index.ts`
- Create: `packages/lens-projectors/tests/runtimeCost.test.ts`

- [ ] **Step 1: Write projection tests**

Create tests that build a v2 state with `safe_waves`, task timing, and withheld reasons, then assert:

```ts
expect(projectRuntimeCostFromState(state)).toMatchObject({
  estimated_waves: 2,
  parallelism_score: expect.any(Number),
  serial_barriers: [expect.objectContaining({ reason: "file_claim" })],
  measured: expect.objectContaining({
    tasks: expect.arrayContaining([expect.objectContaining({ task_id: "task_a" })])
  })
});
```

- [ ] **Step 2: Implement projection**

Create a pure projection that reads only v2 state and returns estimated waves, withheld reasons, measured task durations, wave durations, and dogfood evidence refs when present.

- [ ] **Step 3: Verify and commit**

Run:

```bash
bun test packages/lens-projectors/tests/runtimeCost.test.ts \
  packages/lens-projectors/tests/apply.test.ts
```

Expected: PASS.

Commit:

```bash
git add packages/lens-projectors/src/runtimeCost.ts \
  packages/lens-projectors/src/index.ts \
  packages/lens-projectors/tests/runtimeCost.test.ts
git commit -m "feat: project Waygent runtime cost"
```

### Task 11: Expose Runtime Cost In Inspect, API, And Console

**Files:**
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `apps/api/src/server.ts`
- Modify: `apps/api/tests/api.test.ts`
- Modify: `apps/console/src/uiModel.ts`
- Modify: `apps/console/src/App.tsx`
- Modify: `apps/console/src/uiModel.test.ts`

- [ ] **Step 1: Add failing API/UI model tests**

In `apps/api/tests/api.test.ts`, add an assertion like:

```ts
const detail = await readJson(handler(new Request("http://localhost/runs/run_cost"), { runRoot }));
expect(detail.runtime_cost).toMatchObject({
  estimated_waves: expect.any(Number),
  serial_barriers: expect.any(Array),
  measured: expect.any(Object)
});
```

In `apps/console/src/uiModel.test.ts`, add an assertion like:

```ts
expect(toRunDetailViewModel({
  ...realRunDetailFixture,
  runtime_cost: {
    estimated_waves: 2,
    parallelism_score: 0.5,
    serial_barriers: [{ task_id: "task_b", reason: "file_claim", detail: "conflicts with task_a" }],
    measured: { tasks: [{ task_id: "task_a", duration_ms: 1200 }], waves: [] },
    dogfood: { status: "not_recorded", evidence_refs: [] }
  }
}).sections.map((section) => section.id)).toContain("runtime-cost");
```

- [ ] **Step 2: Wire projection to inspect and API**

Use `projectRuntimeCostFromState(v2State)` wherever real v2 run detail is returned. Do not change apply readiness behavior.

- [ ] **Step 3: Render read-only console evidence**

Add a compact runtime cost section in the console with:

- wave count;
- concurrency used;
- serial barrier reasons;
- task duration list;
- dogfood evidence status.

- [ ] **Step 4: Verify and commit**

Run:

```bash
bun test apps/api/tests apps/console/src packages/orchestrator/tests/runCommandsV2.test.ts
bun run --cwd apps/console build
```

Expected: PASS.

Commit:

```bash
git add packages/orchestrator/src/runCommands.ts \
  apps/api/src/server.ts \
  apps/api/tests/api.test.ts \
  apps/console/src/uiModel.ts \
  apps/console/src/App.tsx \
  apps/console/src/uiModel.test.ts
git commit -m "feat: expose Waygent runtime cost evidence"
```

### Task 12: Document Fast Trusted Waygent Operations

**Files:**
- Modify: `docs/operations/waygent.md`
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/architecture/2026-05-21-waygent-safe-wave-parallel-runtime-design.md`

- [ ] **Step 1: Update operations docs**

Document:

- how safe-wave parallelism is selected;
- how to structure file claims for parallel plans;
- when high-risk or overlapping tasks serialize;
- how to read runtime cost and dogfood evidence;
- why provider claims still require Waygent verification.

- [ ] **Step 2: Run final verification**

Run:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run --cwd apps/console build
git diff --check
```

Optional live smoke:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Expected:

- required commands PASS;
- live smoke PASS when provider CLIs are available and authenticated.

- [ ] **Step 3: Commit**

```bash
git add docs/operations/waygent.md \
  docs/architecture/waygent.md \
  docs/architecture/2026-05-21-waygent-safe-wave-parallel-runtime-design.md
git commit -m "docs: explain fast trusted Waygent operations"
```

## Full Verification Checklist

Run before reporting completion:

```bash
skills/waygent/evals/run.sh
bun run check
bun run platform:demo
bun run check:legacy
bun run waygent:scenarios
bun run --cwd apps/console build
git diff --check
```

Run if the environment has working provider CLIs:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Run if native kernel files are touched:

```bash
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

## Self-Review Result

- Spec coverage: all six design areas are mapped to tasks. Phase 1 covers safe-wave parallel execution, single writer, unique scratch files, provider replay, and timing. Phase 2 covers worktree manager and artifact-index reconciliation. Phase 3 covers cost projection, dogfood evidence, operator surfaces, and docs.
- Red-flag scan: no incomplete markers are intended in this plan.
- Type consistency: new names are `RunExecutionContext`, `WaygentTaskExecutionResult`, `executeBoundedSafeWave`, `resolveWaveConcurrency`, `WorktreeManager`, artifact index helpers, and `projectRuntimeCostFromState`.
