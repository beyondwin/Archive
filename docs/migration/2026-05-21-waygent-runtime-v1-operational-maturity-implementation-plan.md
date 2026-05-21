# Waygent Runtime V1 Operational Maturity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Waygent into a KWS-grade local agent execution runtime with real provider execution, isolated worktrees, task packets, review, verification, recovery, apply, live inspection, and maturity harnesses.

**Architecture:** Waygent remains the single product runtime. The control plane owns state, scheduling, recovery, verification, apply, and AgentLens events; Codex and Claude are bounded provider processes behind common role contracts. `waygent.run_state.v2` becomes the source of truth, while AgentLens events, API, and console are replay and inspection surfaces.

**Tech Stack:** Bun, TypeScript project references, React/Vite, Rust kernel crates, filesystem JSONL, git worktrees, AgentLens Python tests, opt-in Codex and Claude CLIs.

---

## Source Design

- `docs/architecture/2026-05-21-waygent-runtime-v1-operational-maturity-design.md`
- `docs/architecture/2026-05-21-waygent-runtime-agentlens-product-parity-design.md`
- `docs/architecture/waygent.md`
- `docs/operations/waygent.md`

## Non-Negotiable Boundaries

- Do not call `skills/kws-codex-plan-executor` or `skills/kws-claude-multi-agent-executor` from Waygent.
- Do not add active `kws-cpe.*`, `kws-cme.*`, or `kws.orchestrator.*` event namespaces.
- AgentLens is downstream observability. It must not mutate Waygent state.
- Provider output alone never marks a task verified.
- `waygent run` never mutates the source checkout. Only `waygent apply` can.
- Live provider checks stay opt-in and must be skipped by default without local authenticated CLIs.

## File Structure And Ownership

### Contracts

- Modify: `packages/contracts/src/types.ts`
  - Add v2 state, task packet, provider attempt, review, recovery, apply, and completion audit types.
  - Extend `FailureClass` for v1 runtime failures.
- Modify: `packages/contracts/src/schemas.ts`
  - Add JSON schemas for new contracts.
- Modify: `packages/contracts/tests/contracts.test.ts`
  - Contract-level assertions.
- Create: `tests/fixtures/contracts/valid-run-state-v2.json`
- Create: `tests/fixtures/contracts/valid-task-packet.json`
- Create: `tests/fixtures/contracts/valid-review-result.json`
- Create: `tests/fixtures/contracts/valid-provider-attempt.json`

### Orchestrator Core

- Modify: `packages/orchestrator/src/runState.ts`
  - Support v1 read compatibility and v2 write/read helpers.
- Create: `packages/orchestrator/src/stateReconciliation.ts`
  - Detect missing artifacts, completed tasks without evidence, and event/state drift.
- Modify: `packages/orchestrator/src/orchestrator.ts`
  - Replace slice runner with state-machine dispatch.
- Modify: `packages/orchestrator/src/runCommands.ts`
  - Make status, inspect, explain, resume, and apply v2-aware.
- Test: `packages/orchestrator/tests/runStateV2.test.ts`
- Test: `packages/orchestrator/tests/stateReconciliation.test.ts`
- Test: `packages/orchestrator/tests/orchestratorRunV2.test.ts`
- Test: `packages/orchestrator/tests/runCommandsV2.test.ts`

### Context And Task Packets

- Modify: `packages/context-packer/src/taskContext.ts`
  - Build v2 task packets from parsed tasks and spec slices.
- Create: `packages/context-packer/src/taskPacket.ts`
  - Stable packet builder and hashing.
- Test: `packages/context-packer/tests/taskPacket.test.ts`

### Worktree And Kernel

- Modify: `packages/kernel-client/src/worktreeClient.ts`
  - Real worktree creation planning, dirty classification, apply guard.
- Modify: `native/kernel/crates/git-worktree/src/lib.rs`
  - Safe branch/path validation remains Waygent-owned.
- Modify: `packages/kernel-client/src/kernelClient.ts`
  - Use real `executeInProcess` in orchestrator verification.
- Test: `packages/kernel-client/tests/worktreeClient.test.ts`
- Test: `packages/kernel-client/tests/kernelClient.test.ts`

### Provider Adapters

- Modify: `packages/provider-adapters/src/types.ts`
  - Add provider roles, task packet refs, and role-specific result contracts.
- Modify: `packages/provider-adapters/src/processAdapters.ts`
  - Build role-aware prompts, preserve raw artifacts, parse event streams.
- Modify: `packages/provider-adapters/src/codexAdapter.ts`
- Modify: `packages/provider-adapters/src/claudeAdapter.ts`
- Test: `packages/provider-adapters/tests/codexAdapter.test.ts`
- Test: `packages/provider-adapters/tests/claudeAdapter.test.ts`
- Test: `packages/provider-adapters/tests/providerRoles.test.ts`

### Runtime Control

- Modify: `packages/runway-control/src/scheduler.ts`
  - Keep barriers authoritative and add v2 recovery classes.
- Modify: `packages/runway-control/src/projection.ts`
  - Project v2 task states and safe waves.
- Test: `packages/runway-control/tests/barriers.test.ts`
- Test: `packages/runway-control/tests/recovery.test.ts`

### Lens, API, Console

- Modify: `packages/lens-projectors/src/*`
  - Include review, recovery, drift, provider attempts, and v2 apply state.
- Modify: `apps/api/src/server.ts`
  - Serve v2 run details.
- Modify: `apps/console/src/uiModel.ts`
  - Model v2 live run data.
- Modify: `apps/console/src/App.tsx`
  - Read API data instead of only demo snapshot when configured.
- Test: `apps/api/tests/api.test.ts`
- Test: `apps/console/src/uiModel.test.ts`
- Test: `tests/e2e/lens-console-model.test.ts`

### Harness And Operations

- Create: `packages/testkit/src/waygentScenarioHarness.ts`
- Create: `packages/testkit/tests/waygentScenarioHarness.test.ts`
- Create: `tests/waygent-scenarios/*.json`
- Create: `tests/integration/waygent-scenarios.test.ts`
- Create: `tests/integration/waygent-live-provider-smoke.test.ts`
- Modify: `package.json`
  - Add `waygent:scenarios`, `waygent:live-smoke`, and `waygent:dogfood` scripts.
- Modify: `docs/operations/waygent.md`
  - Add v1 maturity verification ladder.

## Execution Order

### Sequential Shared-Core Tasks

1. Task 1 contracts.
2. Task 2 run state v2 and reconciliation.
3. Task 3 task packets.
4. Task 4 worktree and dirty classification.
5. Task 5 real verification.
6. Task 6 provider roles.
7. Task 7 runtime task lifecycle.
8. Task 8 recovery and resume.
9. Task 9 apply materialization.

### Parallel-Safe After Contracts

- Task 10 lens/API/console can start after Task 2 schemas are stable.
- Task 11 scenario harness can start after Task 2 and Task 3.
- Task 12 docs can start after Task 7 but must finish after all behavior lands.

## Task 1: Add Waygent V2 Runtime Contracts

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/contracts/tests/contracts.test.ts`
- Create: `tests/fixtures/contracts/valid-run-state-v2.json`
- Create: `tests/fixtures/contracts/valid-task-packet.json`
- Create: `tests/fixtures/contracts/valid-review-result.json`
- Create: `tests/fixtures/contracts/valid-provider-attempt.json`

- [ ] **Step 1: Add failing contract fixture tests**

Append to `packages/contracts/tests/fixtures.test.ts`:

```ts
test("accepts valid Waygent v2 runtime fixtures", () => {
  for (const fixture of [
    "valid-run-state-v2.json",
    "valid-task-packet.json",
    "valid-review-result.json",
    "valid-provider-attempt.json"
  ]) {
    const payload = JSON.parse(readFileSync(join(fixtureDir, fixture), "utf8"));
    expect(() => validateContract(payload.schema, payload)).not.toThrow();
  }
});
```

- [ ] **Step 2: Create minimal fixture JSON files**

Create `tests/fixtures/contracts/valid-task-packet.json`:

```json
{
  "schema": "waygent.task_packet.v1",
  "run_id": "run_fixture",
  "task_id": "task_fixture",
  "role": "implement",
  "task_title": "Fixture task",
  "plan_excerpt": "Implement fixture task.",
  "spec_excerpt": "Fixture task changes README only.",
  "file_claims": [{ "path": "README.md", "mode": "owned" }],
  "allowed_write_globs": ["README.md"],
  "forbidden_write_globs": [".git/**", "node_modules/**"],
  "dependencies": [],
  "checkpoint_inputs": [],
  "acceptance_commands": ["test -f README.md"],
  "verification_commands": ["test -f README.md"],
  "risk": "low",
  "previous_failures": [],
  "decisions": [],
  "context_budget": { "estimated_chars": 120, "max_chars": 60000, "status": "green" },
  "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
}
```

Create `tests/fixtures/contracts/valid-review-result.json`:

```json
{
  "schema": "runway.review_result.v1",
  "run_id": "run_fixture",
  "task_id": "task_fixture",
  "attempt_id": "attempt_fixture",
  "provider": "fake",
  "verdict": "pass",
  "spec_score": 1,
  "quality_score": 1,
  "findings": [],
  "residual_risk": ["fixture review has no residual risk"],
  "summary": "Review passed."
}
```

Create `tests/fixtures/contracts/valid-provider-attempt.json`:

```json
{
  "schema": "runway.provider_attempt.v1",
  "attempt_id": "attempt_fixture",
  "run_id": "run_fixture",
  "task_id": "task_fixture",
  "role": "implement",
  "provider": "fake",
  "command": ["fake-provider"],
  "cwd": ".",
  "stdin_ref": "artifacts/provider/attempt_fixture.stdin.txt",
  "stdout_ref": "artifacts/provider/attempt_fixture.stdout.txt",
  "stderr_ref": "artifacts/provider/attempt_fixture.stderr.txt",
  "event_stream_ref": null,
  "exit_code": 0,
  "timed_out": false,
  "started_at": "2026-05-21T00:00:00Z",
  "completed_at": "2026-05-21T00:00:01Z",
  "worker_result_ref": "artifacts/provider/attempt_fixture.worker.json",
  "failure_class": null
}
```

Create `tests/fixtures/contracts/valid-run-state-v2.json`:

```json
{
  "schema": "waygent.run_state.v2",
  "run_id": "run_fixture",
  "workspace": "/tmp/source",
  "source_branch": "main",
  "worktree_root": "/tmp/waygent/worktrees",
  "run_root": "/tmp/waygent/runs/run_fixture",
  "artifact_root": "/tmp/waygent/runs/run_fixture/artifacts",
  "state_path": "/tmp/waygent/runs/run_fixture/state.json",
  "event_journal_path": "/tmp/waygent/runs/run_fixture/events.jsonl",
  "plan_path": "plan.md",
  "spec_path": "spec.md",
  "provider_profile": { "provider": "fake", "execution_mode": "multi-agent" },
  "status": "completed",
  "lifecycle_outcome": "finished",
  "current_phase": "complete",
  "tasks": {
    "task_fixture": {
      "id": "task_fixture",
      "status": "verified",
      "risk": "low",
      "dependencies": [],
      "file_claims": [{ "path": "README.md", "mode": "owned" }],
      "attempts": ["attempt_fixture"],
      "task_packet_path": "artifacts/task_packets/task_fixture.json",
      "task_packet_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "unit_manifest": { "allowed_write_globs": ["README.md"], "forbidden_write_globs": [".git/**"] },
      "checkpoint_refs": ["checkpoint_task_fixture"],
      "latest_failure_class": null,
      "decision_packet_ref": null,
      "timing": {}
    }
  },
  "safe_waves": [{ "wave_id": "wave_1", "ready": ["task_fixture"], "withheld": [] }],
  "provider_attempts": [],
  "reviews": [],
  "verification": [],
  "recovery": [],
  "apply": { "status": "not_applied" },
  "context": { "snapshot_path": "artifacts/context.json", "basis_hash": "0000000000000000000000000000000000000000000000000000000000000000" },
  "drift": { "last_checked_at": null, "records": [], "unrepaired_blockers": [] },
  "completion_audit": {
    "status": "passed",
    "required_checks": ["test -f README.md"],
    "verification_evidence": [],
    "review_evidence": [],
    "state_reconciliation": { "passed": true },
    "prompt_to_artifact_checklist": ["task_packet_written", "provider_attempt_recorded"],
    "residual_risk": []
  },
  "timestamps": { "started_at": "2026-05-21T00:00:00Z", "updated_at": "2026-05-21T00:00:01Z", "completed_at": "2026-05-21T00:00:01Z" }
}
```

- [ ] **Step 3: Run fixture tests and verify RED**

Run:

```bash
bun test packages/contracts/tests/fixtures.test.ts
```

Expected: FAIL because the new schema names are not registered.

- [ ] **Step 4: Add TypeScript types**

In `packages/contracts/src/types.ts`, add:

```ts
export type ProviderRole = "implement" | "review" | "fix" | "verify_assist";
export type WaygentRunStatusV2 = "initializing" | "running" | "blocked" | "failed" | "completed" | "applying" | "applied";
export type WaygentLifecycleOutcome = "finished" | "blocked" | "failed" | "aborted" | null;
export type WaygentCurrentPhase = "preflight" | "dispatch" | "review" | "verify" | "recover" | "apply" | "complete";
export type WaygentTaskStatusV2 = "pending" | "ready" | "running" | "needs_fix" | "verified" | "blocked" | "failed" | "applied";

export interface WaygentTaskPacket {
  schema: "waygent.task_packet.v1";
  run_id: string;
  task_id: string;
  role: ProviderRole;
  task_title: string;
  plan_excerpt: string;
  spec_excerpt: string;
  file_claims: Array<{ path: string; mode: "owned" | "shared_append" | "read_only" }>;
  allowed_write_globs: string[];
  forbidden_write_globs: string[];
  dependencies: string[];
  checkpoint_inputs: string[];
  acceptance_commands: string[];
  verification_commands: string[];
  risk: RiskLevel;
  previous_failures: Array<{ failure_class: FailureClass; evidence_refs: string[]; summary: string }>;
  decisions: Array<{ decision_id: string; summary: string }>;
  context_budget: { estimated_chars: number; max_chars: number; status: "green" | "yellow" | "red" };
  sha256: string;
}

export interface ReviewResult {
  schema: "runway.review_result.v1";
  run_id: string;
  task_id: string;
  attempt_id: string;
  provider: string;
  verdict: "pass" | "needs_fix" | "reject";
  spec_score: number;
  quality_score: number;
  findings: Array<{ severity: "critical" | "important" | "minor"; file?: string; line?: number; summary: string }>;
  residual_risk: string[];
  summary: string;
}

export interface ProviderAttempt {
  schema: "runway.provider_attempt.v1";
  attempt_id: string;
  run_id: string;
  task_id: string;
  role: ProviderRole;
  provider: string;
  command: string[];
  cwd: string;
  stdin_ref: string;
  stdout_ref: string;
  stderr_ref: string;
  event_stream_ref: string | null;
  exit_code: number | null;
  timed_out: boolean;
  started_at: string;
  completed_at: string | null;
  worker_result_ref: string | null;
  failure_class: FailureClass | null;
}
```

Also extend `FailureClass` with:

```ts
  | "permission_denied"
  | "service_unreachable"
  | "dependency_missing"
  | "environment_blocker"
  | "flaky_unconfirmed"
  | "command_not_found"
  | "dependency_blocked"
  | "file_claim_conflict"
  | "dirty_source_checkout"
  | "unsafe_apply"
  | "state_drift"
  | "artifact_missing";
```

- [ ] **Step 5: Register schemas**

In `packages/contracts/src/schemas.ts`, add schemas for:

- `waygent.task_packet.v1`
- `runway.review_result.v1`
- `runway.provider_attempt.v1`
- `waygent.run_state.v2`

Use `additionalProperties: false` for top-level objects and `additionalProperties: true` only for embedded flexible metadata such as `provider_profile`.

- [ ] **Step 6: Run contract tests and verify GREEN**

Run:

```bash
bun test packages/contracts/tests
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/contracts tests/fixtures/contracts
git commit -m "feat: add Waygent v2 runtime contracts"
```

## Task 2: Implement V2 Run State And Reconciliation

**Files:**
- Modify: `packages/orchestrator/src/runState.ts`
- Create: `packages/orchestrator/src/stateReconciliation.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Create: `packages/orchestrator/tests/runStateV2.test.ts`
- Create: `packages/orchestrator/tests/stateReconciliation.test.ts`

- [ ] **Step 1: Add failing v2 state read/write tests**

Create `packages/orchestrator/tests/runStateV2.test.ts`:

```ts
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readRunStateV2, runStatePath, writeRunStateV2 } from "../src/runState";

describe("Waygent run state v2", () => {
  test("writes and reads v2 state without breaking v1 helpers", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-state-v2-"));
    writeRunStateV2(root, {
      schema: "waygent.run_state.v2",
      run_id: "run_v2",
      workspace: root,
      source_branch: "main",
      worktree_root: join(root, "worktrees"),
      run_root: join(root, "run_v2"),
      artifact_root: join(root, "run_v2", "artifacts"),
      state_path: runStatePath(root, "run_v2"),
      event_journal_path: join(root, "run_v2", "events.jsonl"),
      plan_path: null,
      spec_path: null,
      provider_profile: { provider: "fake", execution_mode: "multi-agent" },
      status: "initializing",
      lifecycle_outcome: null,
      current_phase: "preflight",
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
      timestamps: { started_at: "2026-05-21T00:00:00Z", updated_at: "2026-05-21T00:00:00Z", completed_at: null }
    });
    expect(readRunStateV2(root, "run_v2")).toMatchObject({ schema: "waygent.run_state.v2", status: "initializing" });
  });
});
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
bun test packages/orchestrator/tests/runStateV2.test.ts
```

Expected: FAIL because `writeRunStateV2` is not exported.

- [ ] **Step 3: Implement v2 helpers**

In `packages/orchestrator/src/runState.ts`, keep existing v1 helpers and add v2 helpers:

```ts
import type { ProviderAttempt, ReviewResult, WaygentTaskPacket } from "@waygent/contracts";

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
  status: "initializing" | "running" | "blocked" | "failed" | "completed" | "applying" | "applied";
  lifecycle_outcome: "finished" | "blocked" | "failed" | "aborted" | null;
  current_phase: "preflight" | "dispatch" | "review" | "verify" | "recover" | "apply" | "complete";
  tasks: Record<string, {
    id: string;
    status: "pending" | "ready" | "running" | "needs_fix" | "verified" | "blocked" | "failed" | "applied";
    risk: "low" | "medium" | "high";
    dependencies: string[];
    file_claims: Array<{ path: string; mode: "owned" | "shared_append" | "read_only" }>;
    attempts: string[];
    task_packet_path: string | null;
    task_packet_sha256: string | null;
    unit_manifest: Record<string, unknown> | null;
    checkpoint_refs: string[];
    latest_failure_class: string | null;
    decision_packet_ref: string | null;
    timing: Record<string, string>;
  }>;
  safe_waves: Array<{ wave_id: string; ready: string[]; withheld: Array<{ task_id: string; reason: string; detail: string }> }>;
  provider_attempts: ProviderAttempt[];
  reviews: ReviewResult[];
  verification: Array<Record<string, unknown>>;
  recovery: Array<Record<string, unknown>>;
  apply: { status: "not_applied" | "blocked" | "applying" | "applied" | "failed"; reason?: string; checkpoint_ref?: string };
  context: { snapshot_path: string | null; basis_hash: string | null };
  drift: { last_checked_at: string | null; records: Array<Record<string, unknown>>; unrepaired_blockers: Array<Record<string, unknown>> };
  completion_audit: null | Record<string, unknown>;
  timestamps: { started_at: string; updated_at: string; completed_at: string | null };
}

export function writeRunStateV2(root: string, state: WaygentRunStateV2): void {
  mkdirSync(join(root, state.run_id), { recursive: true });
  writeFileSync(runStatePath(root, state.run_id), `${JSON.stringify(state, null, 2)}\n`);
}

export function readRunStateV2(root: string, runId: string): WaygentRunStateV2 {
  const parsed = JSON.parse(readFileSync(runStatePath(root, runId), "utf8")) as WaygentRunStateV2;
  if (parsed.schema !== "waygent.run_state.v2") throw new Error(`run ${runId} is not waygent.run_state.v2`);
  return parsed;
}
```

- [ ] **Step 4: Add reconciliation tests**

Create `packages/orchestrator/tests/stateReconciliation.test.ts`:

```ts
import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { reconcileRunState } from "../src/stateReconciliation";
import { writeRunStateV2 } from "../src/runState";

describe("Waygent state reconciliation", () => {
  test("blocks finished states missing task packet artifacts", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-reconcile-"));
    const runRoot = join(root, "run_drift");
    mkdirSync(runRoot, { recursive: true });
    writeRunStateV2(root, {
      schema: "waygent.run_state.v2",
      run_id: "run_drift",
      workspace: root,
      source_branch: "main",
      worktree_root: join(root, "worktrees"),
      run_root: runRoot,
      artifact_root: join(runRoot, "artifacts"),
      state_path: join(runRoot, "state.json"),
      event_journal_path: join(runRoot, "events.jsonl"),
      plan_path: null,
      spec_path: null,
      provider_profile: { provider: "fake" },
      status: "completed",
      lifecycle_outcome: "finished",
      current_phase: "complete",
      tasks: {
        task_a: {
          id: "task_a",
          status: "verified",
          risk: "low",
          dependencies: [],
          file_claims: [{ path: "README.md", mode: "owned" }],
          attempts: [],
          task_packet_path: join(runRoot, "artifacts", "task_packets", "task_a.json"),
          task_packet_sha256: null,
          unit_manifest: { allowed_write_globs: ["README.md"] },
          checkpoint_refs: ["checkpoint_task_a"],
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
      completion_audit: { status: "passed" },
      timestamps: { started_at: "2026-05-21T00:00:00Z", updated_at: "2026-05-21T00:00:00Z", completed_at: "2026-05-21T00:00:00Z" }
    });
    writeFileSync(join(runRoot, "events.jsonl"), "");
    const report = reconcileRunState(root, "run_drift");
    expect(report.passed).toBe(false);
    expect(report.unrepaired_blockers[0]?.type).toBe("artifact_missing");
  });
});
```

- [ ] **Step 5: Implement reconciliation**

Create `packages/orchestrator/src/stateReconciliation.ts`:

```ts
import { existsSync } from "node:fs";
import { readRunStateV2, writeRunStateV2 } from "./runState";

export interface ReconciliationRecord {
  type: "artifact_missing" | "completed_task_missing_unit_manifest" | "finished_without_completion_audit";
  severity: "blocking" | "repairable";
  message: string;
}

export interface ReconciliationReport {
  passed: boolean;
  records: ReconciliationRecord[];
  unrepaired_blockers: ReconciliationRecord[];
}

export function reconcileRunState(root: string, runId: string): ReconciliationReport {
  const state = readRunStateV2(root, runId);
  const records: ReconciliationRecord[] = [];
  for (const task of Object.values(state.tasks)) {
    if (task.status === "verified" && task.task_packet_path && !existsSync(task.task_packet_path)) {
      records.push({ type: "artifact_missing", severity: "blocking", message: `${task.id} task packet is missing` });
    }
    if (task.status === "verified" && !task.unit_manifest) {
      records.push({ type: "completed_task_missing_unit_manifest", severity: "blocking", message: `${task.id} missing unit manifest` });
    }
  }
  if (state.lifecycle_outcome === "finished" && !state.completion_audit) {
    records.push({ type: "finished_without_completion_audit", severity: "blocking", message: "finished run requires completion audit" });
  }
  const unrepaired_blockers = records.filter((record) => record.severity === "blocking");
  writeRunStateV2(root, {
    ...state,
    drift: { last_checked_at: new Date().toISOString(), records, unrepaired_blockers }
  });
  return { passed: unrepaired_blockers.length === 0, records, unrepaired_blockers };
}
```

- [ ] **Step 6: Export and verify**

In `packages/orchestrator/src/index.ts`, export:

```ts
export * from "./stateReconciliation";
```

Run:

```bash
bun test packages/orchestrator/tests/runStateV2.test.ts packages/orchestrator/tests/stateReconciliation.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/orchestrator/src packages/orchestrator/tests
git commit -m "feat: persist Waygent v2 run state"
```

## Task 3: Build Task Packet Artifacts

**Files:**
- Create: `packages/context-packer/src/taskPacket.ts`
- Modify: `packages/context-packer/src/index.ts`
- Modify: `packages/context-packer/package.json`
- Create: `packages/context-packer/tests/taskPacket.test.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`

- [ ] **Step 1: Add failing task packet test**

Create `packages/context-packer/tests/taskPacket.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { buildTaskPacket } from "../src/taskPacket";

describe("Waygent task packets", () => {
  test("builds bounded provider context from task, spec, and failure evidence", () => {
    const packet = buildTaskPacket({
      run_id: "run_packet",
      task: {
        id: "task_a",
        title: "Update README",
        dependencies: [],
        file_claims: [{ path: "README.md", mode: "owned" }],
        risk: "low",
        verification_commands: ["test -f README.md"]
      },
      role: "implement",
      plan_excerpt: "Update README",
      spec_excerpt: "README must exist",
      previous_failures: [{ failure_class: "verification_failed", evidence_refs: ["kernel/verify.json"], summary: "test failed" }]
    });
    expect(packet.schema).toBe("waygent.task_packet.v1");
    expect(packet.allowed_write_globs).toEqual(["README.md"]);
    expect(packet.forbidden_write_globs).toContain(".git/**");
    expect(packet.previous_failures[0]?.failure_class).toBe("verification_failed");
    expect(packet.sha256).toMatch(/^[a-f0-9]{64}$/);
  });
});
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
bun test packages/context-packer/tests/taskPacket.test.ts
```

Expected: FAIL because `taskPacket.ts` does not exist.

- [ ] **Step 3: Implement task packet builder**

Create `packages/context-packer/src/taskPacket.ts`:

```ts
import { createHash } from "node:crypto";
import type { FailureClass, ProviderRole, RiskLevel, WaygentTaskPacket } from "@waygent/contracts";
import type { FileClaim } from "@waygent/runway-control";

export interface TaskPacketTaskInput {
  id: string;
  title: string;
  dependencies: string[];
  file_claims: FileClaim[];
  risk: RiskLevel;
  verification_commands: string[];
}

export interface BuildTaskPacketInput {
  run_id: string;
  task: TaskPacketTaskInput;
  role: ProviderRole;
  plan_excerpt: string;
  spec_excerpt: string;
  checkpoint_inputs?: string[];
  previous_failures?: Array<{ failure_class: FailureClass; evidence_refs: string[]; summary: string }>;
  decisions?: Array<{ decision_id: string; summary: string }>;
  max_chars?: number;
}

export function buildTaskPacket(input: BuildTaskPacketInput): WaygentTaskPacket {
  const base = {
    schema: "waygent.task_packet.v1",
    run_id: input.run_id,
    task_id: input.task.id,
    role: input.role,
    task_title: input.task.title,
    plan_excerpt: input.plan_excerpt,
    spec_excerpt: input.spec_excerpt,
    file_claims: input.task.file_claims,
    allowed_write_globs: input.task.file_claims.filter((claim) => claim.mode !== "read_only").map((claim) => claim.path),
    forbidden_write_globs: [".git/**", "node_modules/**", "native/kernel/target/**", "components/agentlens/.venv/**"],
    dependencies: input.task.dependencies,
    checkpoint_inputs: input.checkpoint_inputs ?? [],
    acceptance_commands: input.task.verification_commands,
    verification_commands: input.task.verification_commands,
    risk: input.task.risk,
    previous_failures: input.previous_failures ?? [],
    decisions: input.decisions ?? [],
    context_budget: { estimated_chars: 0, max_chars: input.max_chars ?? 60000, status: "green" as const },
    sha256: ""
  };
  const estimated = JSON.stringify(base).length;
  const withBudget = {
    ...base,
    context_budget: {
      estimated_chars: estimated,
      max_chars: input.max_chars ?? 60000,
      status: estimated > (input.max_chars ?? 60000) ? "red" as const : estimated > (input.max_chars ?? 60000) * 0.7 ? "yellow" as const : "green" as const
    }
  };
  const sha256 = createHash("sha256").update(JSON.stringify(withBudget, Object.keys(withBudget).sort())).digest("hex");
  return { ...withBudget, sha256 };
}
```

In `packages/context-packer/src/index.ts`, export:

```ts
export * from "./taskPacket";
```

In `packages/context-packer/package.json`, add `@waygent/contracts`:

```json
"dependencies": {
  "@waygent/contracts": "workspace:*",
  "@waygent/runway-control": "workspace:*"
}
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
bun test packages/context-packer/tests/taskPacket.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/context-packer
git commit -m "feat: build Waygent task packets"
```

## Task 4: Add Worktree Lifecycle And Dirty Classification

**Files:**
- Modify: `packages/kernel-client/src/worktreeClient.ts`
- Modify: `native/kernel/crates/git-worktree/src/lib.rs`
- Modify: `packages/kernel-client/tests/worktreeClient.test.ts`
- Create: `packages/orchestrator/src/sourceCheckout.ts`
- Create: `packages/orchestrator/tests/sourceCheckout.test.ts`

- [ ] **Step 1: Add failing dirty classification tests**

Create `packages/orchestrator/tests/sourceCheckout.test.ts`:

```ts
import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { classifySourceCheckout } from "../src/sourceCheckout";

describe("source checkout classification", () => {
  test("classifies dirty files against task file claims", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-source-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "clean\n");
    writeFileSync(join(workspace, "notes.md"), "clean\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "dirty\n");
    mkdirSync(join(workspace, "tmp"), { recursive: true });
    writeFileSync(join(workspace, "tmp", "scratch.txt"), "scratch\n");

    expect(classifySourceCheckout(workspace, [{ path: "README.md", mode: "owned" }])).toMatchObject({
      status: "dirty_related",
      related: ["README.md"]
    });
    expect(classifySourceCheckout(workspace, [{ path: "src/app.ts", mode: "owned" }])).toMatchObject({
      status: "dirty_unrelated"
    });
  });
});
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
bun test packages/orchestrator/tests/sourceCheckout.test.ts
```

Expected: FAIL because `sourceCheckout.ts` does not exist.

- [ ] **Step 3: Implement source classification**

Create `packages/orchestrator/src/sourceCheckout.ts`:

```ts
import { spawnSync } from "node:child_process";
import type { FileClaim } from "@waygent/runway-control";

export type SourceCheckoutStatus = "clean" | "dirty_related" | "dirty_unrelated";

export interface SourceCheckoutClassification {
  status: SourceCheckoutStatus;
  dirty_files: string[];
  related: string[];
  unrelated: string[];
}

export function classifySourceCheckout(workspace: string, claims: FileClaim[]): SourceCheckoutClassification {
  const result = spawnSync("git", ["status", "--porcelain"], { cwd: workspace, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  const dirty_files = result.status === 0
    ? result.stdout.split(/\r?\n/).map((line) => line.slice(3).trim()).filter(Boolean)
    : [];
  const related = dirty_files.filter((file) => claims.some((claim) => samePathFamily(file, claim.path)));
  const unrelated = dirty_files.filter((file) => !related.includes(file));
  return {
    status: dirty_files.length === 0 ? "clean" : related.length > 0 ? "dirty_related" : "dirty_unrelated",
    dirty_files,
    related,
    unrelated
  };
}

function samePathFamily(left: string, right: string): boolean {
  const a = left.replace(/\/+$/, "");
  const b = right.replace(/\/+$/, "");
  return a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`);
}
```

- [ ] **Step 4: Extend worktree client tests**

Append to `packages/kernel-client/tests/worktreeClient.test.ts`:

```ts
test("plans Waygent-owned worktree roots by run and task", () => {
  expect(planWorktree({
    run_id: "run_demo",
    task_id: "task_demo",
    workspace: "/repo",
    worktree_root: "/tmp/waygent-worktrees"
  })).toEqual({
    branch: "waygent/run_demo/task_demo",
    path: "/tmp/waygent-worktrees/run_demo/task_demo",
    source: "/repo"
  });
});
```

- [ ] **Step 5: Run tests**

Run:

```bash
bun test packages/orchestrator/tests/sourceCheckout.test.ts packages/kernel-client/tests/worktreeClient.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator/src/sourceCheckout.ts packages/orchestrator/tests/sourceCheckout.test.ts packages/kernel-client/tests/worktreeClient.test.ts packages/kernel-client/src/worktreeClient.ts native/kernel/crates/git-worktree/src/lib.rs
git commit -m "feat: classify Waygent source checkouts"
```

## Task 5: Execute Verification Commands Through The Kernel Boundary

**Files:**
- Create: `packages/orchestrator/src/verification.ts`
- Create: `packages/orchestrator/tests/verification.test.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/kernel-client/src/kernelClient.ts`
- Modify: `packages/kernel-client/tests/kernelClient.test.ts`

- [ ] **Step 1: Add failing verification test**

Create `packages/orchestrator/tests/verification.test.ts`:

```ts
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runVerificationCommands } from "../src/verification";

describe("Waygent verification", () => {
  test("runs commands and records failure without trusting provider claims", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "waygent-verify-"));
    writeFileSync(join(cwd, "README.md"), "hello\n");
    const result = await runVerificationCommands({
      run_id: "run_verify",
      task_id: "task_verify",
      cwd,
      commands: ["test -f README.md", "test -f missing.txt"]
    });
    expect(result.status).toBe("failed");
    expect(result.results).toHaveLength(2);
    expect(result.results[1]?.exit_code).not.toBe(0);
  });
});
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
bun test packages/orchestrator/tests/verification.test.ts
```

Expected: FAIL because `verification.ts` does not exist.

- [ ] **Step 3: Implement verification runner**

Create `packages/orchestrator/src/verification.ts`:

```ts
import type { KernelExecutionResult } from "@waygent/contracts";
import { buildKernelRequest, executeInProcess } from "@waygent/kernel-client";

export interface VerificationRunInput {
  run_id: string;
  task_id: string;
  cwd: string;
  commands: string[];
  timeout_ms?: number;
}

export interface VerificationRunOutput {
  status: "passed" | "failed";
  results: KernelExecutionResult[];
}

export async function runVerificationCommands(input: VerificationRunInput): Promise<VerificationRunOutput> {
  const results: KernelExecutionResult[] = [];
  for (let index = 0; index < input.commands.length; index += 1) {
    const command = input.commands[index]!;
    const request = buildKernelRequest({
      request_id: `verify_${input.task_id}_${index + 1}`,
      run_id: input.run_id,
      task_id: input.task_id,
      cwd: input.cwd,
      argv: ["bash", "-lc", command],
      timeout_ms: input.timeout_ms ?? 120000
    });
    results.push(await executeInProcess(request));
  }
  return { status: results.every((result) => result.exit_code === 0 && !result.timed_out) ? "passed" : "failed", results };
}
```

- [ ] **Step 4: Run tests**

Run:

```bash
bun test packages/orchestrator/tests/verification.test.ts packages/kernel-client/tests/kernelClient.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/orchestrator/src/verification.ts packages/orchestrator/tests/verification.test.ts packages/kernel-client
git commit -m "feat: run Waygent verification commands"
```

## Task 6: Add Provider Roles And Attempt Artifacts

**Files:**
- Modify: `packages/provider-adapters/src/types.ts`
- Modify: `packages/provider-adapters/src/processAdapters.ts`
- Modify: `packages/provider-adapters/src/codexAdapter.ts`
- Modify: `packages/provider-adapters/src/claudeAdapter.ts`
- Create: `packages/provider-adapters/tests/providerRoles.test.ts`
- Modify: `packages/provider-adapters/tests/codexAdapter.test.ts`
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts`

- [ ] **Step 1: Add failing provider role tests**

Create `packages/provider-adapters/tests/providerRoles.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { buildProviderPrompt } from "../src/processAdapters";

describe("provider role prompts", () => {
  test("includes task packet contract and forbids direct apply or AgentLens writes", () => {
    const prompt = buildProviderPrompt("codex", {
      task_id: "task_a",
      candidate_id: "candidate_task_a",
      role: "implement",
      prompt: "Task body",
      task_packet_path: "/tmp/task_packet.json"
    });
    expect(prompt).toContain("role: implement");
    expect(prompt).toContain("task_packet_path: /tmp/task_packet.json");
    expect(prompt).toContain("Do not write AgentLens events directly.");
    expect(prompt).toContain("Do not apply changes to the source checkout.");
  });
});
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
bun test packages/provider-adapters/tests/providerRoles.test.ts
```

Expected: FAIL because `buildProviderPrompt` is not exported and `AdapterRequest` has no role fields.

- [ ] **Step 3: Extend adapter request types**

In `packages/provider-adapters/src/types.ts`, change `AdapterRequest` to:

```ts
import type { ProviderRole } from "@waygent/contracts";

export interface AdapterRequest {
  task_id: string;
  candidate_id: string;
  role?: ProviderRole;
  prompt: string;
  task_packet_path?: string;
  changed_files?: string[];
}
```

- [ ] **Step 4: Export and strengthen provider prompt**

In `packages/provider-adapters/src/processAdapters.ts`, export `buildProviderPrompt` and replace it with:

```ts
export function buildProviderPrompt(provider: "codex" | "claude", request: AdapterRequest): string {
  return [
    `You are the ${provider} worker for a Waygent task.`,
    `role: ${request.role ?? "implement"}`,
    `task_id: ${request.task_id}`,
    `candidate_id: ${request.candidate_id}`,
    request.task_packet_path ? `task_packet_path: ${request.task_packet_path}` : "task_packet_path: none",
    "Return only one JSON object matching runway.worker_result.v1 unless the provider wrapper emits JSONL envelopes.",
    "Do not write AgentLens events directly.",
    "Do not apply changes to the source checkout.",
    "Edit only the isolated Waygent worktree.",
    "Obey the task packet write policy.",
    "Required JSON fields: schema, task_id, candidate_id, status, changed_files, summary, evidence.",
    "Task prompt:",
    request.prompt
  ].join("\n");
}
```

- [ ] **Step 5: Run provider tests**

Run:

```bash
bun test packages/provider-adapters/tests
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/provider-adapters
git commit -m "feat: add Waygent provider roles"
```

## Task 7: Replace The Slice Runner With A V2 Task Lifecycle

**Files:**
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/src/taskGraph.ts`
- Modify: `packages/orchestrator/src/runEvents.ts`
- Create: `packages/orchestrator/tests/orchestratorRunV2.test.ts`
- Modify: `packages/orchestrator/tests/orchestratorRun.test.ts`

- [ ] **Step 1: Add failing lifecycle test**

Create `packages/orchestrator/tests/orchestratorRunV2.test.ts`:

```ts
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runWaygent } from "../src/orchestrator";
import { readRunStateV2 } from "../src/runState";

const plan = `
\`\`\`yaml waygent-task
id: task_a
title: Create file A
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: low
verify:
  - test -f a.txt
\`\`\`
`;

describe("runWaygent v2 lifecycle", () => {
  test("creates v2 state, task packet, real verification evidence, and completion audit", async () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-run-v2-workspace-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "fixture\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-"));
    await runWaygent({
      root,
      workspace,
      run_id: "run_v2",
      plan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });
    const state = readRunStateV2(root, "run_v2");
    expect(state.schema).toBe("waygent.run_state.v2");
    expect(state.tasks.task_a?.task_packet_path).toBeTruthy();
    expect(state.verification.length).toBeGreaterThan(0);
    expect(state.completion_audit).toMatchObject({ status: "passed" });
  });
});
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorRunV2.test.ts
```

Expected: FAIL because `runWaygent` still writes v1 state and fake verification evidence.

- [ ] **Step 3: Update fake provider to create claimed files only in fake mode**

In `packages/orchestrator/src/orchestrator.ts`, add a helper:

```ts
function materializeFakeProviderResult(worktree: string, task: ParsedWaygentTask): void {
  if (task.file_claims.length === 0) return;
  for (const claim of task.file_claims.filter((item) => item.mode !== "read_only")) {
    const target = join(worktree, claim.path);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, `Waygent fake provider output for ${task.id}\n`);
  }
}
```

Call this helper only when `profile.provider === "fake"` and before verification.

- [ ] **Step 4: Replace v1 completion path with v2 state updates**

In `runWaygent`, after parsing the plan:

- initialize `WaygentRunStateV2`;
- write task packet artifacts for each safe-wave task;
- call provider with `role: "implement"` and `task_packet_path`;
- capture provider attempt records;
- run `runVerificationCommands`;
- set task status to `verified` only when verification passes;
- write completion audit only after `reconcileRunState(...).passed`.

Keep `runWaygentDemo` compatible by passing the demo plan through the v2 path.

- [ ] **Step 5: Run lifecycle tests**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorRunV2.test.ts packages/orchestrator/tests/orchestratorRun.test.ts packages/orchestrator/tests/runCommands.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator/src packages/orchestrator/tests
git commit -m "feat: run Waygent v2 task lifecycle"
```

## Task 8: Implement Review Gate, Recovery, And Real Resume

**Files:**
- Create: `packages/orchestrator/src/reviewGate.ts`
- Create: `packages/orchestrator/src/recoveryExecutor.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/runway-control/src/scheduler.ts`
- Modify: `packages/runway-control/src/projection.ts`
- Create: `packages/orchestrator/tests/reviewGate.test.ts`
- Create: `packages/orchestrator/tests/recoveryExecutor.test.ts`
- Modify: `packages/orchestrator/tests/runCommandsV2.test.ts`

- [ ] **Step 1: Add failing review policy test**

Create `packages/orchestrator/tests/reviewGate.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { shouldReviewTask } from "../src/reviewGate";

describe("Waygent review gate", () => {
  test("requires review for high risk, broad claims, and previous failures", () => {
    expect(shouldReviewTask({ risk: "high", file_claims: [{ path: "README.md", mode: "owned" }], previous_failure_count: 0 })).toBe(true);
    expect(shouldReviewTask({ risk: "low", file_claims: [{ path: ".", mode: "owned" }], previous_failure_count: 0 })).toBe(true);
    expect(shouldReviewTask({ risk: "low", file_claims: [{ path: "README.md", mode: "owned" }], previous_failure_count: 1 })).toBe(true);
    expect(shouldReviewTask({ risk: "low", file_claims: [{ path: "README.md", mode: "owned" }], previous_failure_count: 0 })).toBe(false);
  });
});
```

- [ ] **Step 2: Add failing resume executor test**

Create `packages/orchestrator/tests/recoveryExecutor.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { selectResumeAction } from "../src/recoveryExecutor";

describe("Waygent recovery executor", () => {
  test("selects only unambiguous safe resume actions", () => {
    expect(selectResumeAction({ failure_class: "timeout", retry_count: 0, max_retries: 1, checkpoint_ref: null })).toEqual({
      action: "retry_same_provider",
      automatic: true
    });
    expect(selectResumeAction({ failure_class: "verification_failed", retry_count: 2, max_retries: 2, checkpoint_ref: "ckpt" })).toEqual({
      action: "human_decision",
      automatic: false
    });
    expect(selectResumeAction({ failure_class: "dirty_source_checkout", retry_count: 0, max_retries: 1, checkpoint_ref: "ckpt" })).toEqual({
      action: "human_decision",
      automatic: false
    });
  });
});
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
bun test packages/orchestrator/tests/reviewGate.test.ts packages/orchestrator/tests/recoveryExecutor.test.ts
```

Expected: FAIL because modules do not exist.

- [ ] **Step 4: Implement review gate**

Create `packages/orchestrator/src/reviewGate.ts`:

```ts
import type { FileClaim, RiskLevel } from "@waygent/runway-control";

export function shouldReviewTask(input: { risk: RiskLevel; file_claims: FileClaim[]; previous_failure_count: number }): boolean {
  if (input.risk === "high") return true;
  if (input.previous_failure_count > 0) return true;
  return input.file_claims.some((claim) => claim.mode === "owned" && (claim.path === "." || claim.path === "*" || claim.path.split("/").length <= 1 && claim.path.endsWith("*")));
}
```

- [ ] **Step 5: Implement recovery executor**

Create `packages/orchestrator/src/recoveryExecutor.ts`:

```ts
import type { FailureClass } from "@waygent/contracts";

export interface ResumeActionInput {
  failure_class: FailureClass | string;
  retry_count: number;
  max_retries: number;
  checkpoint_ref: string | null;
}

export interface ResumeActionSelection {
  action: "retry_same_provider" | "retry_switch_provider" | "rerun_verification" | "human_decision";
  automatic: boolean;
}

export function selectResumeAction(input: ResumeActionInput): ResumeActionSelection {
  if (input.failure_class === "timeout" || input.failure_class === "adapter_crashed" || input.failure_class === "malformed_result") {
    return input.retry_count < input.max_retries
      ? { action: "retry_same_provider", automatic: true }
      : { action: "retry_switch_provider", automatic: false };
  }
  if (input.failure_class === "verification_failed") {
    return input.retry_count < input.max_retries
      ? { action: "rerun_verification", automatic: true }
      : { action: "human_decision", automatic: false };
  }
  return { action: "human_decision", automatic: false };
}
```

- [ ] **Step 6: Wire `resumeRun` to v2 state**

In `packages/orchestrator/src/runCommands.ts`, update `resumeRun`:

- if state is v2 and latest blocked task has one automatic action, return that action and call the v2 lifecycle dispatcher;
- if state is v2 and ambiguous, return allowed actions and decision packet ref;
- keep old v1 behavior for old states.

Add `packages/orchestrator/tests/runCommandsV2.test.ts` assertion:

```ts
expect(await resumeRun({ root, run: "run_blocked", dry_run: true })).toMatchObject({
  run_id: "run_blocked",
  allowed_actions: ["human_decision"],
  dry_run: true
});
```

- [ ] **Step 7: Run tests**

Run:

```bash
bun test packages/orchestrator/tests/reviewGate.test.ts packages/orchestrator/tests/recoveryExecutor.test.ts packages/orchestrator/tests/runCommandsV2.test.ts packages/runway-control/tests/recovery.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/orchestrator packages/runway-control
git commit -m "feat: add Waygent review and recovery gates"
```

## Task 9: Materialize Verified Checkpoints On Apply

**Files:**
- Modify: `packages/orchestrator/src/runCommands.ts`
- Create: `packages/orchestrator/src/applyEngine.ts`
- Create: `packages/orchestrator/tests/applyEngine.test.ts`
- Modify: `native/kernel/crates/diff-apply/src/lib.rs`
- Modify: `packages/kernel-client/src/worktreeClient.ts`

- [ ] **Step 1: Add failing apply engine test**

Create `packages/orchestrator/tests/applyEngine.test.ts`:

```ts
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { applyVerifiedCheckpoint } from "../src/applyEngine";

describe("Waygent apply engine", () => {
  test("refuses dirty source and applies clean checkpoint patches", async () => {
    const source = mkdtempSync(join(tmpdir(), "waygent-apply-source-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: source });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: source });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: source });
    writeFileSync(join(source, "README.md"), "before\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: source });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: source });

    const patch = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-before\n+after\n";
    const result = await applyVerifiedCheckpoint({ source, patch, post_apply_commands: ["grep after README.md"] });
    expect(result.status).toBe("applied");
  });
});
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
bun test packages/orchestrator/tests/applyEngine.test.ts
```

Expected: FAIL because `applyEngine.ts` does not exist.

- [ ] **Step 3: Implement apply engine**

Create `packages/orchestrator/src/applyEngine.ts`:

```ts
import { spawnSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { runVerificationCommands } from "./verification";

export interface ApplyVerifiedCheckpointInput {
  source: string;
  patch: string;
  post_apply_commands: string[];
}

export interface ApplyVerifiedCheckpointOutput {
  status: "applied" | "blocked" | "failed";
  reason?: string;
}

export async function applyVerifiedCheckpoint(input: ApplyVerifiedCheckpointInput): Promise<ApplyVerifiedCheckpointOutput> {
  const status = spawnSync("git", ["status", "--porcelain"], { cwd: input.source, encoding: "utf8" });
  if (status.status !== 0 || status.stdout.trim()) return { status: "blocked", reason: "dirty_source_checkout" };
  const patchPath = join(input.source, ".waygent-apply.patch");
  writeFileSync(patchPath, input.patch);
  const apply = spawnSync("git", ["apply", patchPath], { cwd: input.source, encoding: "utf8" });
  spawnSync("rm", ["-f", patchPath], { cwd: input.source });
  if (apply.status !== 0) return { status: "failed", reason: "patch_apply_failed" };
  const verification = await runVerificationCommands({ run_id: "apply", task_id: "post_apply", cwd: input.source, commands: input.post_apply_commands });
  if (verification.status !== "passed") return { status: "failed", reason: "post_apply_verification_failed" };
  return { status: "applied" };
}
```

- [ ] **Step 4: Wire `applyRun`**

In `packages/orchestrator/src/runCommands.ts`, update `applyRun` to:

- reject dirty source before reading checkpoint;
- require v2 `completion_audit.status === "passed"`;
- require a checkpoint or sealed patch artifact;
- call `applyVerifiedCheckpoint`;
- append `runway.apply_completed` only when apply returns `applied`;
- append `runway.apply_blocked` or `runway.apply_failed` otherwise.

- [ ] **Step 5: Run tests**

Run:

```bash
bun test packages/orchestrator/tests/applyEngine.test.ts packages/orchestrator/tests/runCommands.test.ts packages/orchestrator/tests/runCommandsV2.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator native/kernel/crates/diff-apply packages/kernel-client
git commit -m "feat: apply verified Waygent checkpoints"
```

## Task 10: Expose V2 State Through API And Console

**Files:**
- Modify: `apps/api/src/server.ts`
- Modify: `apps/api/tests/api.test.ts`
- Modify: `apps/console/src/uiModel.ts`
- Modify: `apps/console/src/uiModel.test.ts`
- Modify: `apps/console/src/App.tsx`
- Modify: `apps/console/src/styles.css`
- Modify: `tests/e2e/lens-console-model.test.ts`

- [ ] **Step 1: Add failing API v2 detail test**

Append to `apps/api/tests/api.test.ts`:

```ts
test("GET /runs/:runId exposes v2 provider attempts, verification, recovery, and apply readiness", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-api-v2-"));
  await runWaygent({ root, run_id: "run_api_v2", plan: demoPlan, profile: { provider: "fake", execution_mode: "multi-agent" } });
  const response = await handler(new Request("http://local/runs/run_api_v2"), { runRoot: root });
  const payload = await response.json();
  expect(payload).toMatchObject({
    run_id: "run_api_v2",
    state_schema: "waygent.run_state.v2",
    apply_status: "not_ready"
  });
  expect(Array.isArray(payload.provider_attempts)).toBe(true);
  expect(Array.isArray(payload.verification)).toBe(true);
});
```

- [ ] **Step 2: Run API test and verify RED**

Run:

```bash
bun test apps/api/tests/api.test.ts
```

Expected: FAIL because v2 fields are not included.

- [ ] **Step 3: Extend API detail response**

In `apps/api/src/server.ts`, extend `readRealRunDetail`:

```ts
const state = hasRunState(runRoot, runId) ? readRunState(runRoot, runId) : null;
const stateV2 = hasRunState(runRoot, runId) ? tryReadRunStateV2(runRoot, runId) : null;
return {
  ...summarizeRealRun(runRoot, runId),
  state_schema: stateV2?.schema ?? state?.schema ?? null,
  provider_attempts: stateV2?.provider_attempts ?? [],
  reviews: stateV2?.reviews ?? [],
  verification: stateV2?.verification ?? [],
  recovery: stateV2?.recovery ?? [],
  drift: stateV2?.drift ?? null,
  apply: projectApplyState(events),
  apply_status: projectApplyState(events).status,
  safe_wave: safeWaveFromEvents(events),
  failures: projectFailureSummary(events),
  timeline: projectTimeline(events),
  trust: projectTrustReport(events),
  events
};
```

Add a local `tryReadRunStateV2` helper that catches v1 states and returns null.

- [ ] **Step 4: Add console model test**

Append to `apps/console/src/uiModel.test.ts`:

```ts
test("builds live v2 maturity sections", () => {
  const model = buildRunDetailModel({
    run_id: "run_v2",
    status: "completed",
    trust_status: "trusted",
    apply_status: "ready",
    total_events: 8,
    last_event_type: "lens.trust_report_updated",
    safe_wave: ["task_a"],
    failures: [],
    timeline: [],
    provider_attempts: [{ attempt_id: "attempt_1", role: "implement", provider: "fake", exit_code: 0 }],
    verification: [{ verification_id: "verify_1", status: "passed", command: "test -f a.txt" }],
    reviews: [],
    recovery: [],
    drift: { unrepaired_blockers: [] }
  });
  expect(model.sections.map((section) => section.id)).toContain("provider-attempts");
  expect(model.sections.map((section) => section.id)).toContain("verification-evidence");
});
```

- [ ] **Step 5: Update console model and App**

In `apps/console/src/uiModel.ts`, extend `RealRunDetailResponse` with optional:

- `provider_attempts`
- `verification`
- `reviews`
- `recovery`
- `drift`

Extend section IDs:

- `provider-attempts`
- `verification-evidence`
- `review-findings`
- `recovery-decisions`
- `drift`

In `apps/console/src/App.tsx`, keep demo fallback but add API-backed load:

```ts
const apiRoot = import.meta.env.VITE_WAYGENT_API_ROOT as string | undefined;
```

If `apiRoot` is set, fetch `/runs`, then fetch the selected run detail. If fetch fails, show demo data with a non-blocking error banner.

- [ ] **Step 6: Run frontend and API tests**

Run:

```bash
bun test apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts tests/e2e/lens-console-model.test.ts
bun run --cwd apps/console build
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api apps/console tests/e2e
git commit -m "feat: expose Waygent v2 runs in API and console"
```

## Task 11: Build Waygent Scenario Harness, Golden Replay, And Live Smoke

**Files:**
- Create: `packages/testkit/src/waygentScenarioHarness.ts`
- Modify: `packages/testkit/src/index.ts`
- Create: `packages/testkit/tests/waygentScenarioHarness.test.ts`
- Create: `tests/waygent-scenarios/trivial-success.json`
- Create: `tests/waygent-scenarios/overlapping-claims.json`
- Create: `tests/waygent-scenarios/malformed-provider.json`
- Create: `tests/waygent-scenarios/dirty-apply-block.json`
- Create: `tests/waygent-scenarios/missing-checkpoint.json`
- Create: `tests/integration/waygent-scenarios.test.ts`
- Create: `tests/integration/waygent-live-provider-smoke.test.ts`
- Modify: `package.json`

- [ ] **Step 1: Add failing harness unit test**

Create `packages/testkit/tests/waygentScenarioHarness.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { normalizeWaygentRunForGolden } from "../src/waygentScenarioHarness";

describe("Waygent scenario harness", () => {
  test("normalizes machine-local paths and timestamps for golden replay", () => {
    const normalized = normalizeWaygentRunForGolden({
      state: { timestamps: { started_at: "2026-05-21T12:34:56Z" }, workspace: "/Users/kws/source/private/Archive" },
      events: [{ occurred_at: "2026-05-21T12:34:56Z", payload: { path: "/Users/kws/source/private/Archive/a.txt" } }]
    });
    expect(JSON.stringify(normalized)).toContain("<WORKSPACE>");
    expect(JSON.stringify(normalized)).toContain("0000-00-00T00:00:00Z");
  });
});
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
bun test packages/testkit/tests/waygentScenarioHarness.test.ts
```

Expected: FAIL because harness module does not exist.

- [ ] **Step 3: Implement harness helpers**

Create `packages/testkit/src/waygentScenarioHarness.ts`:

```ts
export function normalizeWaygentRunForGolden(input: unknown): unknown {
  const text = JSON.stringify(input)
    .replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z/g, "0000-00-00T00:00:00Z")
    .replace(/\/Users\/[^"]+\/Archive/g, "<WORKSPACE>")
    .replace(/\/private\/var\/folders\/[^"]+/g, "<TMP>");
  return JSON.parse(text);
}
```

Export from `packages/testkit/src/index.ts`:

```ts
export * from "./waygentScenarioHarness";
```

- [ ] **Step 4: Add scenario fixtures**

Create `tests/waygent-scenarios/trivial-success.json`:

```json
{
  "name": "trivial-success",
  "plan": "```yaml waygent-task\nid: task_a\ntitle: Create a file\ndependencies: []\nfile_claims:\n  - path: a.txt\n    mode: owned\nrisk: low\nverify:\n  - test -f a.txt\n```",
  "expected": {
    "status": "completed",
    "task_status": "verified",
    "apply_status": "not_applied"
  }
}
```

Create `tests/waygent-scenarios/overlapping-claims.json`:

```json
{
  "name": "overlapping-claims",
  "plan": "```yaml waygent-task\nid: task_a\ntitle: Create file A\ndependencies: []\nfile_claims:\n  - path: a.txt\n    mode: owned\nrisk: low\nverify:\n  - test -f a.txt\n```\n```yaml waygent-task\nid: task_b\ntitle: Also edit file A\ndependencies: []\nfile_claims:\n  - path: a.txt\n    mode: owned\nrisk: low\nverify:\n  - test -f a.txt\n```",
  "expected": {
    "withheld_reason": "file_claim",
    "ready_count": 1
  }
}
```

Create `tests/waygent-scenarios/malformed-provider.json`:

```json
{
  "name": "malformed-provider",
  "plan": "```yaml waygent-task\nid: task_bad\ntitle: Malformed provider output\ndependencies: []\nfile_claims:\n  - path: bad.txt\n    mode: owned\nrisk: low\nverify:\n  - test -f bad.txt\n```",
  "provider_fixture": {
    "stdout": "this is not json",
    "exit_code": 0
  },
  "expected": {
    "failure_class": "malformed_result",
    "status": "blocked"
  }
}
```

Create `tests/waygent-scenarios/dirty-apply-block.json`:

```json
{
  "name": "dirty-apply-block",
  "plan": "```yaml waygent-task\nid: task_apply\ntitle: Create apply file\ndependencies: []\nfile_claims:\n  - path: apply.txt\n    mode: owned\nrisk: low\nverify:\n  - test -f apply.txt\n```",
  "source_dirty_before_apply": true,
  "expected": {
    "apply_status": "blocked",
    "failure_class": "dirty_source_checkout"
  }
}
```

Create `tests/waygent-scenarios/missing-checkpoint.json`:

```json
{
  "name": "missing-checkpoint",
  "plan": "```yaml waygent-task\nid: task_parent\ntitle: Parent task\ndependencies: []\nfile_claims:\n  - path: parent.txt\n    mode: owned\nrisk: low\nverify:\n  - test -f parent.txt\n```\n```yaml waygent-task\nid: task_child\ntitle: Child task\ndependencies: [task_parent]\nfile_claims:\n  - path: child.txt\n    mode: owned\nrisk: low\nverify:\n  - test -f child.txt\n```",
  "force_missing_checkpoint": "task_parent",
  "expected": {
    "withheld_reason": "checkpoint",
    "failure_class": "missing_checkpoint"
  }
}
```

The scenario runner in Step 5 must read `provider_fixture`, `source_dirty_before_apply`, and `force_missing_checkpoint` fields explicitly.

- [ ] **Step 5: Add integration scenario test**

Create `tests/integration/waygent-scenarios.test.ts`:

```ts
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runWaygent } from "@waygent/orchestrator";

const scenarioDir = join(import.meta.dir, "..", "waygent-scenarios");

describe("Waygent scenario fixtures", () => {
  for (const file of readdirSync(scenarioDir).filter((entry) => entry.endsWith(".json"))) {
    test(file, async () => {
      const scenario = JSON.parse(readFileSync(join(scenarioDir, file), "utf8"));
      const root = await Bun.$`mktemp -d`.text().then((value) => value.trim());
      const result = await runWaygent({ root, plan: scenario.plan, run_id: scenario.name, profile: { provider: "fake", execution_mode: "multi-agent" } });
      expect(result.run_id).toBe(scenario.name);
      expect(result.events.length).toBeGreaterThan(0);
    });
  }
});
```

- [ ] **Step 6: Add live provider smoke test**

Create `tests/integration/waygent-live-provider-smoke.test.ts`:

```ts
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runWaygent } from "@waygent/orchestrator";

describe("Waygent live provider smoke", () => {
  test("is opt-in only", () => {
    const provider = process.env.WAYGENT_LIVE_PROVIDER;
    if (!provider) {
      expect(provider ?? "skip").toBe("skip");
      return;
    }
    expect(["codex", "claude"]).toContain(provider);
  });

  test("runs a disposable live provider fixture when enabled", async () => {
    const provider = process.env.WAYGENT_LIVE_PROVIDER as "codex" | "claude" | undefined;
    if (!provider) return;
    const which = Bun.spawnSync(["which", provider], { stdout: "pipe", stderr: "pipe" });
    expect(which.exitCode).toBe(0);
    const workspace = mkdtempSync(join(tmpdir(), "waygent-live-workspace-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "live smoke\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
    const root = mkdtempSync(join(tmpdir(), "waygent-live-runs-"));
    const plan = "```yaml waygent-task\nid: task_live\ntitle: Touch live smoke file\ndependencies: []\nfile_claims:\n  - path: live.txt\n    mode: owned\nrisk: low\nverify:\n  - test -f live.txt\n```";
    const result = await runWaygent({
      root,
      workspace,
      plan,
      run_id: `live_${provider}`,
      profile: { provider, execution_mode: "multi-agent" }
    });
    expect(result.run_id).toBe(`live_${provider}`);
  });
});
```

- [ ] **Step 7: Add package scripts**

In root `package.json`, add:

```json
"waygent:scenarios": "bun test tests/integration/waygent-scenarios.test.ts",
"waygent:live-smoke": "bun test tests/integration/waygent-live-provider-smoke.test.ts",
"waygent:dogfood": "bun run waygent:scenarios"
```

- [ ] **Step 8: Run harness tests**

Run:

```bash
bun test packages/testkit/tests/waygentScenarioHarness.test.ts tests/integration/waygent-scenarios.test.ts tests/integration/waygent-live-provider-smoke.test.ts
bun run waygent:scenarios
```

Expected: PASS; live provider test skips unless `WAYGENT_LIVE_PROVIDER` is set.

- [ ] **Step 9: Commit**

```bash
git add packages/testkit tests/waygent-scenarios tests/integration package.json
git commit -m "test: add Waygent maturity scenarios"
```

## Task 12: Operations Docs And Full Verification Closure

**Files:**
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/operations/waygent.md`
- Modify: `skills/waygent/README.md`
- Modify: `skills/waygent/references/commands.md`
- Modify: `skills/waygent/evals/check_skill_contract.py`

- [ ] **Step 1: Update operations verification ladder**

In `docs/operations/waygent.md`, add:

````markdown
## V1 Maturity Verification

Default offline gate:

```bash
skills/waygent/evals/run.sh
bun run check
bun run platform:demo
bun run check:legacy
bun run waygent:scenarios
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
cd components/agentlens && .venv/bin/python -m pytest -q
```

Opt-in live provider gate:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```
````

- [ ] **Step 2: Update skill command references**

In `skills/waygent/references/commands.md`, document:

```markdown
waygent run --plan <path> --provider codex --execution-mode multi-agent
waygent run --plan <path> --provider claude --execution-mode multi-agent
waygent inspect --last --json
waygent explain --last
waygent resume --last
waygent apply --run <run_id>
```

Add stop rules for:

- dirty related source checkout;
- ambiguous active run;
- live provider CLI unavailable;
- failed verification;
- apply without verified checkpoint.

- [ ] **Step 3: Extend skill eval**

In `skills/waygent/evals/check_skill_contract.py`, add checks that the skill docs mention:

- `waygent:scenarios`
- `WAYGENT_LIVE_PROVIDER`
- `dirty_source_checkout`
- `verified checkpoint`
- `resume --last`

- [ ] **Step 4: Run full verification**

Run Bun verification:

```bash
skills/waygent/evals/run.sh
bun run check
bun run platform:demo
bun run check:legacy
bun run waygent:scenarios
bun run --cwd apps/console build
```

Run Rust verification:

```bash
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

Run AgentLens verification:

```bash
cd components/agentlens
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -e '.[test]'
fi
.venv/bin/python -m pytest -q
```

Expected:

- Waygent skill eval passes.
- Bun check passes.
- Platform demo prints a trusted run.
- Legacy check rejects active KWS/AgentRunway routing.
- Scenario harness passes.
- Console builds.
- Rust format, clippy, and tests pass.
- AgentLens pytest passes.

- [ ] **Step 5: Final hygiene**

Run:

```bash
git status --short --branch --untracked-files=all
git diff --check
```

Expected: no unintended generated artifacts staged or unstaged. Ignored runtime directories may exist but must not be staged.

- [ ] **Step 6: Commit final docs**

```bash
git add docs/architecture/waygent.md docs/operations/waygent.md skills/waygent
git commit -m "docs: document Waygent v1 operations"
```

## Final Completion Criteria

This implementation is complete only when:

- `waygent.run_state.v2` is the authoritative state for new runs;
- v1 run readers remain compatible with old runs;
- task packet artifacts are written for provider dispatch;
- real verification commands execute through the kernel boundary;
- provider output alone cannot mark a task verified;
- review gate is risk and evidence aware;
- blocked tasks create actionable recovery decisions;
- `waygent resume --last` can safely continue unambiguous v2 runs;
- `waygent apply` materializes only verified checkpoints and blocks dirty sources;
- API and console can inspect v2 run state and evidence;
- scenario harness and golden replay foundations exist;
- live provider smoke is opt-in and skipped by default;
- no active runtime path depends on KWS executor skills;
- full verification in Task 12 passes.

## Self-Review Notes

- The plan keeps KWS as a reference, not a runtime dependency.
- The plan preserves Waygent event namespaces and `check:legacy`.
- The shared-core tasks are sequential because they touch contracts, state, orchestrator lifecycle, and apply semantics.
- API/console, harness, and docs can be parallelized only after the v2 state shape stabilizes.
