# Waygent Lens No-Python Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a TypeScript-first Lens inspection path so real `waygent run` output is visible through CLI, API, and console, then delete the legacy Python AgentLens tree.

**Architecture:** `waygent.run_state.v2`, `agentlens.event.v3`, and run artifacts remain the durable source of truth. `packages/lens-store` verifies artifact health, `packages/lens-projectors` builds one `WaygentRunInspection` model, and `apps/api`, `apps/console`, and `waygent inspect/explain` consume that same model. Python `components/agentlens` is removed only after the TypeScript path has parity.

**Tech Stack:** Bun, TypeScript project references, React/Vite, filesystem JSON/JSONL artifacts, `@waygent/contracts`, `@waygent/lens-store`, `@waygent/lens-projectors`, `@waygent/orchestrator`.

---

## Source Design

- Design: `docs/superpowers/specs/2026-05-22-waygent-lens-no-python-observability-design.md`
- Architecture index: `docs/architecture/waygent.md`
- Active event contract: `docs/contracts/events.md`

## Scope Check

This plan covers one migration program with sequential dependencies:

1. active docs stop directing new work into Python AgentLens;
2. TypeScript inspection model is added;
3. API, console, and CLI switch to that model;
4. Python AgentLens is deleted after parity is proven.

The tasks intentionally stay sequential because later deletion is unsafe until
the shared projection and reader surfaces pass real-run tests.

## File Structure

### Documentation And Routing

- `AGENTS.md`: active repository instructions; remove Python AgentLens as an active surface and mark it legacy pending deletion.
- `CLAUDE.md`: remove Python AgentLens check suggestions from active default checks.
- `docs/architecture/waygent.md`: state the active Lens architecture.
- `docs/contracts/events.md`: state `agentlens.event.v3` and no Python schema path.

### Contracts

- `packages/contracts/src/types.ts`: define TypeScript inspection and artifact-health types.
- `packages/contracts/src/index.ts`: keep existing barrel export.

### Artifact Health

- `packages/lens-store/src/artifactHealth.ts`: collect and verify critical run artifact refs from `waygent.run_state.v2`.
- `packages/lens-store/src/index.ts`: export artifact-health helpers.
- `packages/lens-store/tests/artifactHealth.test.ts`: verify present, missing, sha mismatch, byte-length mismatch, and absolute task-packet path handling.

### Projection

- `packages/lens-projectors/src/inspection.ts`: build `WaygentRunInspection` from events, v2 state, optional state error, and artifact health.
- `packages/lens-projectors/src/index.ts`: export the inspection projector.
- `packages/lens-projectors/tests/inspection.test.ts`: cover completed, blocked, missing-state, invalid-state, and artifact-drift cases.

### API

- `apps/api/src/server.ts`: use shared artifact health and inspection projector for list/detail/trust/failure routes.
- `apps/api/tests/api.test.ts`: assert real run detail uses the shared projection.
- `apps/api/tests/events.test.ts`: keep event stream behavior and add projection-backed run snapshot assertions.

### Console

- `apps/console/src/uiModel.ts`: map API inspection responses into a display model without recomputing readiness.
- `apps/console/src/uiModel.test.ts`: replace scattered-field fixtures with projection-shaped fixtures.
- `apps/console/src/App.tsx`: render overview, safe waves, tasks, evidence, trust, apply, artifacts, and recovery from the model.
- `apps/console/src/styles.css`: productize the inspection layout.

### CLI

- `packages/orchestrator/src/runCommands.ts`: add shared inspection builder and route `inspectRun`/`explainRun` through it.
- `packages/orchestrator/tests/runCommands.test.ts`: assert inspect/explain projection output.
- `packages/orchestrator/tests/runCommandsV2.test.ts`: assert readiness and artifact-health behavior.
- `apps/cli/tests/cli.test.ts`: assert CLI output includes inspection fields.

### Python Deletion

- remove `components/agentlens/`.
- update active docs and scripts that mention Python AgentLens.
- keep historical migration references only when clearly historical.

## Execution Order

- Sequential tasks: Task 1 through Task 10 in order.
- Parallel-safe tasks after Task 3: none in the default plan, because API, console, and CLI all depend on the same projection shape.
- Human approval gates: after Task 5 API parity, after Task 8 CLI parity, before Task 9 Python deletion.

---

### Task 1: Lock Active Lens Direction In Docs

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/contracts/events.md`

- [ ] **Step 1: Update root active surface guidance**

In `AGENTS.md`, replace the current AgentLens active component bullets with this text:

```markdown
Archive is now focused on these active Waygent surfaces:

- `apps/cli/` - the Waygent CLI.
- `apps/api/` - the local Waygent read API.
- `apps/console/` - the Waygent console app.
- `packages/lens-store/` and `packages/lens-projectors/` - the active Lens
  storage and projection path.
- `packages/orchestrator/`, `packages/runway-control/`,
  `packages/provider-adapters/`, and `native/kernel/` - the Waygent runtime.
- `skills/` - source of truth for local skills shared by Codex and Claude Code.

Waygent is the approved brand for the unified agent platform and user-facing
orchestrator. Lens is the TypeScript projection and inspection layer inside
Waygent. The legacy Python `components/agentlens/` tree is unsupported and is
scheduled for deletion; do not add new behavior there.
```

- [ ] **Step 2: Remove active Python verification guidance**

In `AGENTS.md`, replace the AgentLens backend verification block with:

```bash
# Waygent runtime and Lens projections
bun run check
bun run platform:demo
bun run waygent:scenarios

# Waygent console
cd apps/console
bun test src
bun run build

# Native kernel
cd native/kernel && cargo test --workspace

# Generic patch hygiene
git diff --check
```

- [ ] **Step 3: Update Claude routing guidance**

In `CLAUDE.md`, replace the useful checks block with:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
cd apps/console && bun test src && bun run build
cd native/kernel && cargo test --workspace
cd skills/kws-claude-multi-agent-executor && ./evals/run.sh
git diff --check
```

Add this sentence under the Claude-specific notes:

```markdown
- Do not route active Lens work into `components/agentlens`; that Python tree is
  legacy and is scheduled for deletion after TypeScript Lens parity.
```

- [ ] **Step 4: Update architecture docs**

In `docs/architecture/waygent.md`, replace the opening paragraph with:

```markdown
Waygent is the user-facing agent platform. The control plane is Bun and
TypeScript; the execution kernel is Rust; Lens storage and projections live in
`packages/lens-store` and `packages/lens-projectors`; API and console expose
those projections to operators.
```

Add this paragraph after the active event family sentence:

```markdown
The legacy Python `components/agentlens` implementation is not an active
Waygent product surface. New run inspection work uses the TypeScript Lens path
and the Python tree is removed in the no-Python observability migration.
```

- [ ] **Step 5: Update event contract docs**

In `docs/contracts/events.md`, replace the final paragraph with:

```markdown
Waygent owns active runtime events. Lens reads those events through
`packages/lens-store` and `packages/lens-projectors`. Python AgentLens schemas
and projections are not part of the active event contract.
```

- [ ] **Step 6: Verify docs**

Run:

```bash
git diff --check -- AGENTS.md CLAUDE.md docs/architecture/waygent.md docs/contracts/events.md
```

Expected: command exits 0 with no output.

- [ ] **Step 7: Commit docs direction**

Run:

```bash
git add AGENTS.md CLAUDE.md docs/architecture/waygent.md docs/contracts/events.md
git commit -m "docs: route Lens work to TypeScript"
```

Expected: commit succeeds.

---

### Task 2: Add Inspection Contract Types

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Test: `packages/contracts/tests/contracts.test.ts`

- [ ] **Step 1: Write failing contract test**

Append this test to `packages/contracts/tests/contracts.test.ts`:

```ts
test("WaygentRunInspection type supports run evidence shape", () => {
  const inspection = {
    schema: "waygent.run_inspection.v1",
    run_id: "run_contract",
    status: "ok",
    header: {
      run_id: "run_contract",
      workspace: "/workspace",
      run_status: "completed",
      lifecycle_outcome: "finished",
      current_phase: "complete",
      source_branch: "main",
      started_at: "2026-05-22T00:00:00.000Z",
      updated_at: "2026-05-22T00:01:00.000Z",
      completed_at: "2026-05-22T00:01:00.000Z"
    },
    safe_waves: [],
    tasks: [],
    provider_attempts: [],
    verification: [],
    trust: { trust_status: "trusted", evidence_score: 1, reasons: ["verified"] },
    failures: [],
    apply_readiness: {
      status: "ready",
      reason: null,
      checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
      combined_patch_ref: "artifacts/checkpoints/apply/run_contract.patch",
      source: "run_state_v2"
    },
    artifacts: [],
    events: [],
    issues: []
  } satisfies import("../src/types").WaygentRunInspection;

  expect(inspection.schema).toBe("waygent.run_inspection.v1");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
```

Expected: FAIL with TypeScript error that `WaygentRunInspection` is not exported.

- [ ] **Step 3: Add contract types**

Add these interfaces after `ApplyReadinessProjection` in `packages/contracts/src/types.ts`:

```ts
export type WaygentInspectionStatus = "ok" | "partial" | "missing" | "invalid";

export interface WaygentInspectionIssue {
  code:
    | "missing_events"
    | "missing_run_state_v2"
    | "invalid_run_state_v2"
    | "unsupported_run_state"
    | "artifact_missing"
    | "artifact_digest_mismatch"
    | "artifact_byte_length_mismatch"
    | "projection_partial";
  severity: "info" | "warning" | "error";
  summary: string;
  ref?: string;
}

export interface WaygentArtifactHealth {
  ref: string;
  label: string;
  phase: "task_packet" | "provider" | "worker" | "verification" | "checkpoint" | "apply" | "recovery";
  task_id: string | null;
  required_for_apply: boolean;
  status: "present" | "missing" | "digest_mismatch" | "byte_length_mismatch";
  expected_sha256: string | null;
  actual_sha256: string | null;
  expected_byte_length: number | null;
  actual_byte_length: number | null;
}

export interface WaygentRunInspection {
  schema: "waygent.run_inspection.v1";
  run_id: string;
  status: WaygentInspectionStatus;
  header: {
    run_id: string;
    workspace: string | null;
    run_status: WaygentRunStatusV2 | RunStatus | "unknown";
    lifecycle_outcome: WaygentLifecycleOutcome;
    current_phase: WaygentCurrentPhase | "unknown";
    source_branch: string | null;
    started_at: string | null;
    updated_at: string | null;
    completed_at: string | null;
  };
  safe_waves: WaygentRunStateV2["safe_waves"];
  tasks: Array<WaygentRunStateTaskV2 & { title: string; owner: string; latest_event_type: string | null }>;
  provider_attempts: ProviderAttempt[];
  verification: Array<Record<string, unknown>>;
  reviews: ReviewResult[];
  recovery: Array<Record<string, unknown>>;
  trust: {
    trust_status: "trusted" | "failed" | "insufficient_evidence";
    evidence_score: number;
    reasons: string[];
  };
  failures: Array<{
    task_id: string;
    failure_class: FailureClass | "unknown";
    recovery_action: string;
    count: number;
  }>;
  apply_readiness: ApplyReadinessProjection;
  artifacts: WaygentArtifactHealth[];
  events: Array<{
    event_id: string;
    sequence: number;
    event_type: string;
    phase: string;
    outcome: EventOutcome;
    severity: EventSeverity;
    trust_impact: TrustImpact;
    summary: string;
  }>;
  issues: WaygentInspectionIssue[];
}
```

- [ ] **Step 4: Run contract test**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit contract types**

Run:

```bash
git add packages/contracts/src/types.ts packages/contracts/tests/contracts.test.ts
git commit -m "feat: add Waygent inspection contract"
```

Expected: commit succeeds.

---

### Task 3: Add Artifact Health Collection

**Files:**
- Create: `packages/lens-store/src/artifactHealth.ts`
- Modify: `packages/lens-store/src/index.ts`
- Test: `packages/lens-store/tests/artifactHealth.test.ts`

- [ ] **Step 1: Write failing artifact health tests**

Create `packages/lens-store/tests/artifactHealth.test.ts`:

```ts
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { collectWaygentArtifactHealth, sha256 } from "../src";

function state(root: string): WaygentRunStateV2 {
  const runRoot = join(root, "run_artifacts");
  return {
    schema: "waygent.run_state.v2",
    run_id: "run_artifacts",
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
        attempts: ["attempt_task_a_1"],
        task_packet_path: join(runRoot, "artifacts/task_packets/task_a.json"),
        task_packet_sha256: "",
        unit_manifest: { title: "Task A" },
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        latest_failure_class: null,
        decision_packet_ref: null,
        timing: {}
      }
    },
    safe_waves: [],
    provider_attempts: [
      {
        schema: "runway.provider_attempt.v1",
        attempt_id: "attempt_task_a_1",
        run_id: "run_artifacts",
        task_id: "task_a",
        role: "implement",
        provider: "fake",
        command: ["fake-provider"],
        cwd: root,
        stdin_ref: "artifacts/provider/attempt_task_a_1.stdin.txt",
        stdout_ref: "artifacts/provider/attempt_task_a_1.stdout.txt",
        stderr_ref: "artifacts/provider/attempt_task_a_1.stderr.txt",
        event_stream_ref: null,
        exit_code: 0,
        timed_out: false,
        started_at: "2026-05-22T00:00:00.000Z",
        completed_at: "2026-05-22T00:01:00.000Z",
        worker_result_ref: "artifacts/worker/task_a.json",
        failure_class: null
      }
    ],
    reviews: [],
    verification: [
      {
        verification_id: "verify_task_a_1",
        task_id: "task_a",
        command: "printf hello",
        kernel_result_ref: "artifacts/kernel/verify_task_a_1.json",
        status: "passed"
      }
    ],
    recovery: [],
    apply: { status: "not_applied" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: {
      status: "passed",
      combined_apply_evidence: {
        status: "passed",
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        patch_ref: "artifacts/checkpoints/apply/run_artifacts.patch",
        patch_sha256: "",
        patch_byte_length: 0
      }
    },
    timestamps: {
      started_at: "2026-05-22T00:00:00.000Z",
      updated_at: "2026-05-22T00:01:00.000Z",
      completed_at: "2026-05-22T00:01:00.000Z"
    }
  };
}

describe("collectWaygentArtifactHealth", () => {
  test("reports present artifacts with matching digests", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-artifact-health-"));
    const runRoot = join(root, "run_artifacts");
    const packet = "{}\n";
    const patch = "diff --git a/README.md b/README.md\n";
    const s = state(root);
    writeFileSync(join(runRoot, "artifacts/task_packets/task_a.json"), packet);
    writeFileSync(join(runRoot, "artifacts/checkpoints/apply/run_artifacts.patch"), patch);
    s.tasks.task_a!.task_packet_sha256 = sha256(packet);
    (s.completion_audit as any).combined_apply_evidence.patch_sha256 = sha256(patch);
    (s.completion_audit as any).combined_apply_evidence.patch_byte_length = Buffer.byteLength(patch);

    const health = collectWaygentArtifactHealth(s);

    expect(health.find((item) => item.label === "task_packet")?.status).toBe("present");
    expect(health.find((item) => item.label === "combined_apply_patch")?.status).toBe("present");
  });

  test("reports missing and digest-mismatched artifacts", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-artifact-health-missing-"));
    const runRoot = join(root, "run_artifacts");
    const s = state(root);
    writeFileSync(join(runRoot, "artifacts/task_packets/task_a.json"), "changed\n");
    s.tasks.task_a!.task_packet_sha256 = "a".repeat(64);

    const health = collectWaygentArtifactHealth(s);

    expect(health.find((item) => item.label === "task_packet")?.status).toBe("digest_mismatch");
    expect(health.find((item) => item.label === "combined_apply_patch")?.status).toBe("missing");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
bun test packages/lens-store/tests/artifactHealth.test.ts
```

Expected: FAIL because `collectWaygentArtifactHealth` is not exported.

- [ ] **Step 3: Implement artifact health collector**

Create `packages/lens-store/src/artifactHealth.ts`:

```ts
import { existsSync, readFileSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import type { WaygentArtifactHealth, WaygentRunStateV2 } from "@waygent/contracts";
import { sha256 } from "./artifactStore";

interface ArtifactCandidate {
  ref: string | null | undefined;
  label: string;
  phase: WaygentArtifactHealth["phase"];
  task_id: string | null;
  required_for_apply: boolean;
  expected_sha256?: string | null;
  expected_byte_length?: number | null;
}

export function collectWaygentArtifactHealth(state: WaygentRunStateV2): WaygentArtifactHealth[] {
  return artifactCandidates(state)
    .filter((candidate): candidate is ArtifactCandidate & { ref: string } => typeof candidate.ref === "string" && candidate.ref.length > 0)
    .map((candidate) => inspectArtifact(state.run_root, candidate));
}

function artifactCandidates(state: WaygentRunStateV2): ArtifactCandidate[] {
  const candidates: ArtifactCandidate[] = [];
  for (const task of Object.values(state.tasks)) {
    candidates.push({
      ref: task.task_packet_path,
      label: "task_packet",
      phase: "task_packet",
      task_id: task.id,
      required_for_apply: false,
      expected_sha256: task.task_packet_sha256
    });
    for (const checkpointRef of task.checkpoint_refs) {
      candidates.push({
        ref: checkpointRef,
        label: "checkpoint_manifest",
        phase: "checkpoint",
        task_id: task.id,
        required_for_apply: true
      });
    }
    if (task.decision_packet_ref) {
      candidates.push({
        ref: task.decision_packet_ref,
        label: "decision_packet",
        phase: "recovery",
        task_id: task.id,
        required_for_apply: false
      });
    }
  }

  for (const attempt of state.provider_attempts) {
    candidates.push({ ref: attempt.stdin_ref, label: "provider_stdin", phase: "provider", task_id: attempt.task_id, required_for_apply: false });
    candidates.push({ ref: attempt.stdout_ref, label: "provider_stdout", phase: "provider", task_id: attempt.task_id, required_for_apply: false });
    candidates.push({ ref: attempt.stderr_ref, label: "provider_stderr", phase: "provider", task_id: attempt.task_id, required_for_apply: false });
    candidates.push({ ref: attempt.worker_result_ref, label: "worker_result", phase: "worker", task_id: attempt.task_id, required_for_apply: false });
    candidates.push({ ref: attempt.event_stream_ref, label: "provider_event_stream", phase: "provider", task_id: attempt.task_id, required_for_apply: false });
  }

  for (const record of state.verification) {
    candidates.push({
      ref: typeof record.kernel_result_ref === "string" ? record.kernel_result_ref : null,
      label: "kernel_result",
      phase: "verification",
      task_id: typeof record.task_id === "string" ? record.task_id : null,
      required_for_apply: true
    });
  }

  const combined = (state.completion_audit as {
    combined_apply_evidence?: {
      patch_ref?: unknown;
      patch_sha256?: unknown;
      patch_byte_length?: unknown;
    };
  } | null)?.combined_apply_evidence;
  candidates.push({
    ref: typeof combined?.patch_ref === "string" ? combined.patch_ref : null,
    label: "combined_apply_patch",
    phase: "apply",
    task_id: null,
    required_for_apply: true,
    expected_sha256: typeof combined?.patch_sha256 === "string" ? combined.patch_sha256 : null,
    expected_byte_length: typeof combined?.patch_byte_length === "number" ? combined.patch_byte_length : null
  });

  return candidates;
}

function inspectArtifact(runRoot: string, candidate: ArtifactCandidate & { ref: string }): WaygentArtifactHealth {
  const absolute = isAbsolute(candidate.ref) ? candidate.ref : join(runRoot, candidate.ref);
  if (!existsSync(absolute)) {
    return {
      ref: candidate.ref,
      label: candidate.label,
      phase: candidate.phase,
      task_id: candidate.task_id,
      required_for_apply: candidate.required_for_apply,
      status: "missing",
      expected_sha256: candidate.expected_sha256 ?? null,
      actual_sha256: null,
      expected_byte_length: candidate.expected_byte_length ?? null,
      actual_byte_length: null
    };
  }

  const bytes = readFileSync(absolute);
  const actualSha = sha256(bytes);
  const actualBytes = bytes.byteLength;
  const shaMismatch = candidate.expected_sha256 && candidate.expected_sha256 !== actualSha;
  const byteMismatch = typeof candidate.expected_byte_length === "number" && candidate.expected_byte_length !== actualBytes;

  return {
    ref: candidate.ref,
    label: candidate.label,
    phase: candidate.phase,
    task_id: candidate.task_id,
    required_for_apply: candidate.required_for_apply,
    status: shaMismatch ? "digest_mismatch" : byteMismatch ? "byte_length_mismatch" : "present",
    expected_sha256: candidate.expected_sha256 ?? null,
    actual_sha256: actualSha,
    expected_byte_length: candidate.expected_byte_length ?? null,
    actual_byte_length: actualBytes
  };
}
```

- [ ] **Step 4: Export artifact health collector**

Add this line to `packages/lens-store/src/index.ts`:

```ts
export * from "./artifactHealth";
```

- [ ] **Step 5: Run lens-store tests**

Run:

```bash
bun test packages/lens-store/tests/artifactHealth.test.ts packages/lens-store/tests/artifactStore.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit artifact health**

Run:

```bash
git add packages/lens-store/src/artifactHealth.ts packages/lens-store/src/index.ts packages/lens-store/tests/artifactHealth.test.ts
git commit -m "feat: collect Waygent artifact health"
```

Expected: commit succeeds.

---

### Task 4: Add Waygent Run Inspection Projector

**Files:**
- Create: `packages/lens-projectors/src/inspection.ts`
- Modify: `packages/lens-projectors/src/index.ts`
- Test: `packages/lens-projectors/tests/inspection.test.ts`

- [ ] **Step 1: Write failing projector tests**

Create `packages/lens-projectors/tests/inspection.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import type { AgentLensEvent, WaygentRunStateV2 } from "@waygent/contracts";
import { buildRunEvent } from "@waygent/orchestrator";
import { projectWaygentRunInspection } from "../src";

function event(sequence: number, event_type: string, outcome: AgentLensEvent["outcome"] = "success"): AgentLensEvent {
  return buildRunEvent({
    run_id: "run_inspect",
    sequence,
    event_type,
    phase: event_type.split(".")[0] ?? "runway",
    outcome,
    summary: `${event_type} summary`,
    payload: event_type === "runway.safe_wave_selected" ? { safe_wave: ["task_a"], wave_id: "wave_1" } : {}
  });
}

function state(): WaygentRunStateV2 {
  return {
    schema: "waygent.run_state.v2",
    run_id: "run_inspect",
    workspace: "/workspace",
    source_branch: "main",
    worktree_root: "/tmp/worktrees",
    run_root: "/tmp/run_inspect",
    artifact_root: "/tmp/run_inspect/artifacts",
    state_path: "/tmp/run_inspect/state.json",
    event_journal_path: "/tmp/run_inspect/events.jsonl",
    plan_path: "/workspace/plan.md",
    spec_path: "/workspace/spec.md",
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
        attempts: ["attempt_task_a_1"],
        task_packet_path: "/tmp/run_inspect/artifacts/task_packets/task_a.json",
        task_packet_sha256: "a".repeat(64),
        unit_manifest: { title: "Task A" },
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        latest_failure_class: null,
        decision_packet_ref: null,
        timing: { started: "2026-05-22T00:00:00.000Z" }
      }
    },
    safe_waves: [{ wave_id: "wave_1", ready: ["task_a"], withheld: [], concurrency: 1 }],
    provider_attempts: [],
    reviews: [],
    verification: [{ task_id: "task_a", command: "printf hello", status: "passed" }],
    recovery: [],
    apply: { status: "not_applied" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: { status: "passed", combined_apply_evidence: { status: "passed", checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"], patch_ref: "artifacts/checkpoints/apply/run_inspect.patch" } },
    timestamps: {
      started_at: "2026-05-22T00:00:00.000Z",
      updated_at: "2026-05-22T00:01:00.000Z",
      completed_at: "2026-05-22T00:01:00.000Z"
    }
  };
}

describe("projectWaygentRunInspection", () => {
  test("projects completed run state, trust, readiness, tasks, and events", () => {
    const inspection = projectWaygentRunInspection({
      run_id: "run_inspect",
      state: state(),
      events: [
        event(1, "platform.run_started", "running"),
        event(2, "runway.safe_wave_selected"),
        event(3, "runway.verification_result"),
        event(4, "lens.trust_report_updated")
      ],
      artifacts: []
    });

    expect(inspection.status).toBe("ok");
    expect(inspection.header.run_status).toBe("completed");
    expect(inspection.trust.trust_status).toBe("trusted");
    expect(inspection.apply_readiness.status).toBe("ready");
    expect(inspection.tasks[0]).toMatchObject({ id: "task_a", title: "Task A", latest_event_type: null });
    expect(inspection.events.map((item) => item.event_type)).toContain("runway.verification_result");
  });

  test("marks missing state as partial and not ready", () => {
    const inspection = projectWaygentRunInspection({
      run_id: "run_missing_state",
      state: null,
      state_error: "missing_run_state_v2",
      events: [event(1, "platform.run_started", "running")],
      artifacts: []
    });

    expect(inspection.status).toBe("partial");
    expect(inspection.apply_readiness).toMatchObject({
      status: "not_ready",
      reason: "missing_run_state_v2"
    });
    expect(inspection.issues[0]).toMatchObject({
      code: "missing_run_state_v2",
      severity: "error"
    });
  });

  test("surfaces artifact drift as an inspection issue", () => {
    const inspection = projectWaygentRunInspection({
      run_id: "run_inspect",
      state: state(),
      events: [event(1, "runway.verification_result")],
      artifacts: [
        {
          ref: "artifacts/checkpoints/apply/run_inspect.patch",
          label: "combined_apply_patch",
          phase: "apply",
          task_id: null,
          required_for_apply: true,
          status: "digest_mismatch",
          expected_sha256: "a".repeat(64),
          actual_sha256: "b".repeat(64),
          expected_byte_length: null,
          actual_byte_length: 10
        }
      ]
    });

    expect(inspection.status).toBe("partial");
    expect(inspection.issues.some((issue) => issue.code === "artifact_digest_mismatch")).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
bun test packages/lens-projectors/tests/inspection.test.ts
```

Expected: FAIL because `projectWaygentRunInspection` is not exported.

- [ ] **Step 3: Implement projector**

Create `packages/lens-projectors/src/inspection.ts`:

```ts
import type {
  AgentLensEvent,
  ApplyReadinessProjection,
  WaygentArtifactHealth,
  WaygentInspectionIssue,
  WaygentRunInspection,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectApplyReadinessFromState } from "./apply";
import { projectFailureSummary, projectTimeline, projectTrustReport } from "./trust";

export interface WaygentRunInspectionInput {
  run_id: string;
  events: AgentLensEvent[];
  state: WaygentRunStateV2 | null;
  state_error?: string | null;
  artifacts: WaygentArtifactHealth[];
}

export function projectWaygentRunInspection(input: WaygentRunInspectionInput): WaygentRunInspection {
  const issues = inspectionIssues(input);
  const trust = projectTrustReport(input.events);
  const readiness = input.state
    ? projectApplyReadinessFromState(input.state)
    : notReady(input.state_error ?? "missing_run_state_v2");
  const status = issues.some((issue) => issue.severity === "error") ? "partial" : "ok";

  return {
    schema: "waygent.run_inspection.v1",
    run_id: input.run_id,
    status,
    header: {
      run_id: input.run_id,
      workspace: input.state?.workspace ?? null,
      run_status: input.state?.status ?? "unknown",
      lifecycle_outcome: input.state?.lifecycle_outcome ?? null,
      current_phase: input.state?.current_phase ?? "unknown",
      source_branch: input.state?.source_branch ?? null,
      started_at: input.state?.timestamps.started_at ?? null,
      updated_at: input.state?.timestamps.updated_at ?? null,
      completed_at: input.state?.timestamps.completed_at ?? null
    },
    safe_waves: input.state?.safe_waves ?? [],
    tasks: input.state
      ? Object.values(input.state.tasks).map((task) => ({
        ...task,
        title: titleFromTask(task.unit_manifest, task.id),
        owner: ownerForTask(input.state!, task.id),
        latest_event_type: latestEventForTask(input.events, task.id)
      }))
      : [],
    provider_attempts: input.state?.provider_attempts ?? [],
    verification: input.state?.verification ?? [],
    reviews: input.state?.reviews ?? [],
    recovery: input.state?.recovery ?? [],
    trust,
    failures: projectFailureSummary(input.events),
    apply_readiness: readiness,
    artifacts: input.artifacts,
    events: projectTimeline(input.events).map((event) => {
      const source = input.events.find((candidate) => candidate.sequence === event.sequence);
      return {
        event_id: source?.event_id ?? `event_${input.run_id}_${event.sequence}`,
        sequence: event.sequence,
        event_type: event.event_type,
        phase: event.phase,
        outcome: source?.outcome ?? "success",
        severity: source?.severity ?? "info",
        trust_impact: source?.trust_impact ?? "neutral",
        summary: event.summary
      };
    }),
    issues
  };
}

function notReady(reason: string): ApplyReadinessProjection {
  return {
    status: "not_ready",
    reason,
    checkpoint_refs: [],
    combined_patch_ref: null,
    source: "events"
  };
}

function inspectionIssues(input: WaygentRunInspectionInput): WaygentInspectionIssue[] {
  const issues: WaygentInspectionIssue[] = [];
  if (input.events.length === 0) {
    issues.push({ code: "missing_events", severity: "error", summary: "Run has no event journal entries." });
  }
  if (!input.state) {
    issues.push({
      code: input.state_error === "invalid_run_state_v2" ? "invalid_run_state_v2" : input.state_error === "unsupported_run_state" ? "unsupported_run_state" : "missing_run_state_v2",
      severity: "error",
      summary: input.state_error ?? "missing_run_state_v2"
    });
  }
  for (const artifact of input.artifacts) {
    if (artifact.status === "present") continue;
    issues.push({
      code: artifact.status === "missing"
        ? "artifact_missing"
        : artifact.status === "digest_mismatch"
          ? "artifact_digest_mismatch"
          : "artifact_byte_length_mismatch",
      severity: artifact.required_for_apply ? "error" : "warning",
      summary: `${artifact.label} ${artifact.status}`,
      ref: artifact.ref
    });
  }
  return issues;
}

function titleFromTask(unitManifest: Record<string, unknown> | null, fallback: string): string {
  const title = unitManifest?.title;
  return typeof title === "string" && title.length > 0 ? title : fallback;
}

function ownerForTask(state: WaygentRunStateV2, taskId: string): string {
  const attempt = state.provider_attempts.find((candidate) => candidate.task_id === taskId);
  return attempt?.provider ?? "waygent";
}

function latestEventForTask(events: AgentLensEvent[], taskId: string): string | null {
  const event = [...events].reverse().find((candidate) => {
    const payload = candidate.payload;
    if (payload.task_id === taskId) return true;
    const worker = payload.worker;
    return Boolean(worker && typeof worker === "object" && (worker as Record<string, unknown>).task_id === taskId);
  });
  return event?.event_type ?? null;
}
```

- [ ] **Step 4: Export projector**

Add this line to `packages/lens-projectors/src/index.ts`:

```ts
export * from "./inspection";
```

- [ ] **Step 5: Run projector tests**

Run:

```bash
bun test packages/lens-projectors/tests/inspection.test.ts packages/lens-projectors/tests/apply.test.ts packages/lens-projectors/tests/trust.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit projector**

Run:

```bash
git add packages/lens-projectors/src/inspection.ts packages/lens-projectors/src/index.ts packages/lens-projectors/tests/inspection.test.ts
git commit -m "feat: project Waygent run inspection"
```

Expected: commit succeeds.

---

### Task 5: Route API Detail Through Inspection Projection

**Files:**
- Modify: `apps/api/src/server.ts`
- Modify: `apps/api/tests/api.test.ts`
- Modify: `apps/api/tests/events.test.ts`

- [ ] **Step 1: Add failing API test for projection-backed detail**

Append this test to `apps/api/tests/api.test.ts`:

```ts
test("GET /runs/:runId returns shared Waygent inspection", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-api-inspection-"));
  const runId = "run_api_inspection";
  await runWaygentDemo({ root, run_id: runId });
  const realHandler = createApiHandler({ runRoot: root });

  const response = await realHandler(new Request(`http://waygent.local/runs/${runId}`));
  const detail = await response.json();

  expect(detail.inspection).toMatchObject({
    schema: "waygent.run_inspection.v1",
    run_id: runId,
    status: "ok"
  });
  expect(detail.inspection.tasks[0]).toMatchObject({
    id: "task_demo",
    status: "verified"
  });
  expect(detail.inspection.apply_readiness.status).toBe("ready");
  expect(detail.inspection.artifacts.some((item: { label: string }) => item.label === "combined_apply_patch")).toBe(true);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
bun test apps/api/tests/api.test.ts
```

Expected: FAIL because `detail.inspection` is undefined.

- [ ] **Step 3: Add API inspection helper imports**

In `apps/api/src/server.ts`, extend imports:

```ts
import { projectWaygentRunInspection } from "@waygent/lens-projectors";
import { collectWaygentArtifactHealth } from "@waygent/lens-store";
```

- [ ] **Step 4: Build inspection in real run detail**

In `readRealRunDetail`, after `const applyReadiness = ...`, add:

```ts
  const artifactHealth = stateV2 ? collectWaygentArtifactHealth(stateV2) : [];
  const inspection = projectWaygentRunInspection({
    run_id: runId,
    state: stateV2,
    state_error: stateV2 ? null : "missing_run_state_v2",
    events,
    artifacts: artifactHealth
  });
```

In the returned object from `readRealRunDetail`, add:

```ts
    inspection,
```

- [ ] **Step 5: Make list summary read inspection status**

In `summarizeRealRun`, compute inspection and use it:

```ts
  const artifactHealth = stateV2 ? collectWaygentArtifactHealth(stateV2) : [];
  const inspection = projectWaygentRunInspection({
    run_id: runId,
    state: stateV2,
    state_error: stateV2 ? null : "missing_run_state_v2",
    events,
    artifacts: artifactHealth
  });
```

Then set:

```ts
    status: stateV2 ? runStatusFromV2(stateV2.status) : statusFromEvents(events, trust.trust_status),
    trust_status: inspection.trust.trust_status,
    apply_status: inspection.apply_readiness.status,
```

- [ ] **Step 6: Add missing-state API assertion**

Append to the existing missing-v2-state test in `apps/api/tests/api.test.ts`:

```ts
    expect(detail.inspection).toMatchObject({
      status: "partial",
      apply_readiness: {
        status: "not_ready",
        reason: "missing_run_state_v2"
      }
    });
```

- [ ] **Step 7: Run API tests**

Run:

```bash
bun test apps/api/tests
```

Expected: PASS.

- [ ] **Step 8: Commit API projection route**

Run:

```bash
git add apps/api/src/server.ts apps/api/tests/api.test.ts apps/api/tests/events.test.ts
git commit -m "feat: expose Waygent inspection through API"
```

Expected: commit succeeds.

---

### Task 6: Make Console Model API-First

**Files:**
- Modify: `apps/console/src/uiModel.ts`
- Modify: `apps/console/src/uiModel.test.ts`

- [ ] **Step 1: Add failing console model test**

Append this test to `apps/console/src/uiModel.test.ts`:

```ts
test("maps shared inspection response without recomputing readiness", () => {
  const run = realRunDetailToConsoleRun({
    run_id: "run_console_projection",
    status: "completed",
    trust_status: "trusted",
    apply_status: "ready",
    total_events: 4,
    last_event_type: "lens.trust_report_updated",
    safe_wave: ["task_a"],
    failures: [],
    timeline: [],
    inspection: {
      schema: "waygent.run_inspection.v1",
      run_id: "run_console_projection",
      status: "ok",
      header: {
        run_id: "run_console_projection",
        workspace: "/workspace",
        run_status: "completed",
        lifecycle_outcome: "finished",
        current_phase: "complete",
        source_branch: "main",
        started_at: "2026-05-22T00:00:00.000Z",
        updated_at: "2026-05-22T00:01:00.000Z",
        completed_at: "2026-05-22T00:01:00.000Z"
      },
      safe_waves: [{ wave_id: "wave_1", ready: ["task_a"], withheld: [], concurrency: 1 }],
      tasks: [{
        id: "task_a",
        status: "verified",
        risk: "low",
        dependencies: [],
        file_claims: [{ path: "README.md", mode: "owned" }],
        attempts: ["attempt_task_a_1"],
        task_packet_path: "artifacts/task_packets/task_a.json",
        task_packet_sha256: "a".repeat(64),
        unit_manifest: { title: "Task A" },
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        latest_failure_class: null,
        decision_packet_ref: null,
        timing: {},
        title: "Task A",
        owner: "fake",
        latest_event_type: "runway.verification_result"
      }],
      provider_attempts: [],
      verification: [],
      reviews: [],
      recovery: [],
      trust: { trust_status: "trusted", evidence_score: 2, reasons: ["verification evidence"] },
      failures: [],
      apply_readiness: {
        status: "ready",
        reason: null,
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        combined_patch_ref: "artifacts/checkpoints/apply/run_console_projection.patch",
        source: "run_state_v2"
      },
      artifacts: [{
        ref: "artifacts/checkpoints/apply/run_console_projection.patch",
        label: "combined_apply_patch",
        phase: "apply",
        task_id: null,
        required_for_apply: true,
        status: "present",
        expected_sha256: null,
        actual_sha256: "b".repeat(64),
        expected_byte_length: null,
        actual_byte_length: 12
      }],
      events: [],
      issues: []
    }
  });

  expect(run.title).toBe("run_console_projection");
  expect(run.tasks[0]).toMatchObject({
    taskId: "task_a",
    title: "Task A",
    owner: "fake",
    checkpoint: "artifacts/checkpoints/task_a/candidate_task_a.json"
  });
  expect(run.applyStatus).toMatchObject({
    state: "ready",
    canApply: true,
    combinedPatchRef: "artifacts/checkpoints/apply/run_console_projection.patch"
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
bun test apps/console/src/uiModel.test.ts
```

Expected: FAIL because `RealRunDetailResponse` does not include `inspection`.

- [ ] **Step 3: Add inspection response types**

In `apps/console/src/uiModel.ts`, add these interfaces near `RealRunDetailResponse`:

```ts
export interface ConsoleInspection {
  schema: "waygent.run_inspection.v1";
  run_id: string;
  status: "ok" | "partial" | "missing" | "invalid";
  header: Record<string, unknown>;
  safe_waves: Array<{ wave_id: string; ready: string[]; withheld: Array<{ task_id: string; reason: string; detail?: string }>; concurrency?: number }>;
  tasks: Array<Record<string, unknown> & { id: string; title: string; owner: string; checkpoint_refs: string[]; status: string }>;
  provider_attempts: Array<Record<string, unknown>>;
  verification: Array<Record<string, unknown>>;
  reviews: Array<Record<string, unknown>>;
  recovery: Array<Record<string, unknown>>;
  trust: { trust_status: string; evidence_score: number; reasons: string[] };
  failures: Array<{ task_id: string; failure_class: string; recovery_action: string; count: number }>;
  apply_readiness: {
    status: ApplyState;
    reason: string | null;
    checkpoint_refs: string[];
    combined_patch_ref: string | null;
    source: "run_state_v2" | "events";
  };
  artifacts: Array<Record<string, unknown> & { ref: string; label: string; status: string; required_for_apply: boolean }>;
  events: Array<Record<string, unknown>>;
  issues: Array<{ code: string; severity: string; summary: string; ref?: string }>;
}
```

Add to `RealRunDetailResponse`:

```ts
  inspection?: ConsoleInspection;
```

- [ ] **Step 4: Prefer inspection in realRunDetailToConsoleRun**

At the top of `realRunDetailToConsoleRun`, add:

```ts
  if (response.inspection) {
    const inspection = response.inspection;
    return {
      runId: response.run_id,
      title: response.run_id,
      status: consoleStatus(String(inspection.header.run_status ?? response.status)),
      trust: {
        verdict: trustVerdict(inspection.trust.trust_status),
        score: trustScore(inspection.trust.trust_status),
        reasons: inspection.trust.reasons
      },
      tasks: inspection.tasks.map((task) => ({
        taskId: task.id,
        title: task.title,
        status: task.status,
        owner: task.owner,
        checkpoint: task.checkpoint_refs.join(", ")
      })),
      events: eventsFromRealDetail(response),
      failures: inspection.failures.map((failure) => ({
        taskId: failure.task_id,
        failureClass: failure.failure_class,
        recoveryAction: failure.recovery_action,
        summary: `${failure.failure_class} occurred ${failure.count} time${failure.count === 1 ? "" : "s"}.`
      })),
      decisionPackets: inspection.recovery.map((record) => ({
        taskId: stringValue(record.task_id) || "run",
        failureClass: stringValue(record.failure_class) || "recovery_required",
        allowedActions: stringArray(record.allowed_actions),
        blockedActions: stringArray(record.blocked_actions),
        summary: stringValue(record.recommended_next_action) || "Recovery decision is required."
      })),
      applyStatus: {
        state: inspection.apply_readiness.status,
        canApply: inspection.apply_readiness.status === "ready",
        dirtySourceCheckout: inspection.issues.some((issue) => issue.code === "dirty_source_checkout"),
        reason: inspection.apply_readiness.reason ?? inspection.apply_readiness.status,
        checkpointRef: inspection.apply_readiness.checkpoint_refs.join(", "),
        checkpointRefs: inspection.apply_readiness.checkpoint_refs,
        combinedPatchRef: inspection.apply_readiness.combined_patch_ref
      }
    };
  }
```

- [ ] **Step 5: Extend RunDetailModel with inspection**

Add to `RunDetailModel`:

```ts
  inspection: ConsoleInspection | null;
```

In `buildRunDetailModel`, add:

```ts
    inspection: response.inspection ?? null,
```

- [ ] **Step 6: Run console model tests**

Run:

```bash
bun test apps/console/src/uiModel.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit console model alignment**

Run:

```bash
git add apps/console/src/uiModel.ts apps/console/src/uiModel.test.ts
git commit -m "feat: map console from Waygent inspection"
```

Expected: commit succeeds.

---

### Task 7: Productize Console Inspection Surface

**Files:**
- Modify: `apps/console/src/App.tsx`
- Modify: `apps/console/src/styles.css`
- Modify: `apps/console/src/uiModel.test.ts`

- [ ] **Step 1: Add render coverage for inspection sections**

Append a text snapshot assertion to `apps/console/src/uiModel.test.ts`:

```ts
test("render snapshot includes readiness evidence from inspection", () => {
  const model = buildConsoleUiModel(demoConsoleSnapshot, "run_demo_blocked");
  const snapshot = renderConsoleSnapshot(model);

  expect(snapshot).toContain("apply: blocked");
  expect(snapshot).toContain("verification_failed");
});
```

- [ ] **Step 2: Add console components**

In `apps/console/src/App.tsx`, add these components above `OperationalEvidence`:

```tsx
function SafeWaves({ detail }: { detail: RunDetailModel }) {
  const waves = detail.inspection?.safe_waves ?? [];
  return (
    <section className="section-band" aria-labelledby="safe-waves-heading">
      <h2 id="safe-waves-heading">Safe Waves</h2>
      {waves.length === 0 ? (
        <p className="empty-state">No safe-wave evidence</p>
      ) : (
        <div className="wave-stack">
          {waves.map((wave) => (
            <article className="wave-row" key={wave.wave_id}>
              <strong>{wave.wave_id}</strong>
              <span>ready: {wave.ready.join(", ") || "none"}</span>
              <span>concurrency: {wave.concurrency ?? 1}</span>
              <p>
                withheld: {wave.withheld.map((item) => `${item.task_id}:${item.reason}`).join(", ") || "none"}
              </p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ArtifactHealth({ detail }: { detail: RunDetailModel }) {
  const artifacts = detail.inspection?.artifacts ?? [];
  return (
    <section className="section-band compact evidence-list" aria-label="Artifact health">
      <h2>Artifacts</h2>
      {artifacts.length === 0 ? (
        <p className="empty-state">No artifact health evidence</p>
      ) : (
        artifacts.map((artifact) => (
          <article className={`artifact-row ${String(artifact.status)}`} key={`${artifact.label}-${artifact.ref}`}>
            <strong>{artifact.label}</strong>
            <span>{artifact.status}</span>
            <p>{artifact.ref}</p>
            <small>{artifact.required_for_apply ? "required for apply" : "supporting evidence"}</small>
          </article>
        ))
      )}
    </section>
  );
}

function InspectionIssues({ detail }: { detail: RunDetailModel }) {
  const issues = detail.inspection?.issues ?? [];
  return (
    <section className="section-band compact evidence-list" aria-label="Inspection issues">
      <h2>Inspection Issues</h2>
      {issues.length === 0 ? (
        <p className="empty-state">No inspection issues</p>
      ) : (
        issues.map((issue) => (
          <article className={`issue-row ${issue.severity}`} key={`${issue.code}-${issue.ref ?? issue.summary}`}>
            <strong>{issue.code}</strong>
            <span>{issue.severity}</span>
            <p>{issue.summary}</p>
          </article>
        ))
      )}
    </section>
  );
}
```

- [ ] **Step 3: Render new sections**

In `App.tsx`, place `<SafeWaves detail={detail} />` immediately after the run-detail section. Add `<ArtifactHealth detail={detail} />` and `<InspectionIssues detail={detail} />` inside the lower projection grid after `<OperationalEvidence detail={detail} />` by replacing:

```tsx
          <OperationalEvidence detail={detail} />
```

with:

```tsx
          <OperationalEvidence detail={detail} />
          <div className="projection-grid lower-grid">
            <ArtifactHealth detail={detail} />
            <InspectionIssues detail={detail} />
          </div>
```

- [ ] **Step 4: Add console styles**

Append to `apps/console/src/styles.css`:

```css
.wave-stack {
  display: grid;
  gap: 8px;
}

.wave-row,
.artifact-row,
.issue-row {
  border: 1px solid #e2e7e2;
  border-radius: 6px;
  display: grid;
  gap: 6px;
  padding: 10px;
}

.wave-row p,
.artifact-row p,
.issue-row p {
  margin: 0;
  overflow-wrap: anywhere;
}

.artifact-row.missing,
.artifact-row.digest_mismatch,
.artifact-row.byte_length_mismatch,
.issue-row.error {
  border-left: 4px solid #c2413b;
}

.artifact-row.present,
.issue-row.info {
  border-left: 4px solid #1f8a5b;
}

.issue-row.warning {
  border-left: 4px solid #b66a13;
}

.lower-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
```

- [ ] **Step 5: Run console tests and build**

Run:

```bash
bun test apps/console/src
bun run --cwd apps/console build
```

Expected: both commands PASS.

- [ ] **Step 6: Commit console surface**

Run:

```bash
git add apps/console/src/App.tsx apps/console/src/styles.css apps/console/src/uiModel.test.ts
git commit -m "feat: show Waygent inspection evidence in console"
```

Expected: commit succeeds.

---

### Task 8: Align CLI Inspect And Explain

**Files:**
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/orchestrator/tests/runCommands.test.ts`
- Modify: `packages/orchestrator/tests/runCommandsV2.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`

- [ ] **Step 1: Add failing orchestrator inspect test**

Append this test to `packages/orchestrator/tests/runCommandsV2.test.ts`:

```ts
test("inspectRun returns shared Waygent inspection", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-inspect-command-"));
  await runWaygentDemo({ root, run_id: "run_cli_inspect" });

  const result = inspectRun({ root, run: "run_cli_inspect" });

  expect(result.inspection).toMatchObject({
    schema: "waygent.run_inspection.v1",
    run_id: "run_cli_inspect",
    status: "ok"
  });
  expect(result.inspection.apply_readiness.status).toBe("ready");
});
```

- [ ] **Step 2: Add failing explain test**

Append this test to `packages/orchestrator/tests/runCommandsV2.test.ts`:

```ts
test("explainRun summarizes inspection readiness", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-explain-command-"));
  await runWaygentDemo({ root, run_id: "run_cli_explain" });

  const result = explainRun({ root, run: "run_cli_explain" });

  expect(result).toMatchObject({
    run_id: "run_cli_explain",
    readiness: "ready",
    trust_status: "trusted"
  });
  expect(result.summary).toContain("ready");
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
bun test packages/orchestrator/tests/runCommandsV2.test.ts
```

Expected: FAIL because `inspection`, `readiness`, and `trust_status` are missing.

- [ ] **Step 4: Add shared inspection builder**

In `packages/orchestrator/src/runCommands.ts`, extend imports:

```ts
import { collectWaygentArtifactHealth } from "@waygent/lens-store";
import { projectWaygentRunInspection } from "@waygent/lens-projectors";
```

Add this helper near `inspectRun`:

```ts
function buildInspection(root: string, runId: string) {
  const events = readEvents(runPaths(root, runId).events);
  const stateResult = readRunStateV2Result(root, runId);
  const state = stateResult.status === "ok" ? stateResult.state : null;
  return projectWaygentRunInspection({
    run_id: runId,
    events,
    state,
    state_error: stateResult.status === "ok" ? null : stateResult.reason,
    artifacts: state ? collectWaygentArtifactHealth(state) : []
  });
}
```

- [ ] **Step 5: Return inspection from inspectRun**

Update the `inspectRun` return type to include:

```ts
  inspection: ReturnType<typeof buildInspection>;
```

Inside `inspectRun`, add:

```ts
  const inspection = buildInspection(options.root, status.run_id);
```

Return:

```ts
    inspection,
```

- [ ] **Step 6: Return readiness and trust from explainRun**

Replace `explainRun` with:

```ts
export function explainRun(options: RunCommandOptions): {
  run_id: string;
  blocked_by: FailureClass | "unknown" | null;
  trust_status: string;
  readiness: string;
  next_action: string;
  summary: string;
} {
  const runId = resolveRunId(options);
  const inspection = buildInspection(options.root, runId);
  const failure = inspection.failures[0] ?? null;
  const readiness = inspection.apply_readiness.status;
  const nextAction = failure
    ? failure.recovery_action
    : readiness === "ready"
      ? "apply_verified_checkpoint"
      : "inspect_run";
  return {
    run_id: runId,
    blocked_by: failure?.failure_class ?? null,
    trust_status: inspection.trust.trust_status,
    readiness,
    next_action: nextAction,
    summary: failure
      ? `${failure.task_id} blocked by ${failure.failure_class}; next action ${nextAction}`
      : `run is ${inspection.header.run_status}; trust ${inspection.trust.trust_status}; apply ${readiness}`
  };
}
```

- [ ] **Step 7: Update CLI tests**

In `apps/cli/tests/cli.test.ts`, add:

```ts
test("inspect CLI returns shared inspection", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-cli-inspection-"));
  await runCli(["demo", "--root", root, "--run", "run_cli_projection"]);

  const output = await runCli(["inspect", "--root", root, "--run", "run_cli_projection"]);

  expect((output as any).inspection).toMatchObject({
    schema: "waygent.run_inspection.v1",
    run_id: "run_cli_projection"
  });
});
```

- [ ] **Step 8: Run CLI and orchestrator tests**

Run:

```bash
bun test packages/orchestrator/tests/runCommandsV2.test.ts apps/cli/tests/cli.test.ts
```

Expected: PASS.

- [ ] **Step 9: Commit CLI alignment**

Run:

```bash
git add packages/orchestrator/src/runCommands.ts packages/orchestrator/tests/runCommands.test.ts packages/orchestrator/tests/runCommandsV2.test.ts apps/cli/tests/cli.test.ts
git commit -m "feat: align inspect and explain with Lens inspection"
```

Expected: commit succeeds.

---

### Task 9: Delete Legacy Python AgentLens

**Files:**
- Delete: `components/agentlens/`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/contracts/events.md`
- Modify: any active docs found by the search commands below.

- [ ] **Step 1: Verify TypeScript Lens parity before deletion**

Run:

```bash
bun test packages/lens-store/tests/artifactHealth.test.ts packages/lens-projectors/tests/inspection.test.ts apps/api/tests apps/console/src packages/orchestrator/tests/runCommandsV2.test.ts apps/cli/tests/cli.test.ts
bun run --cwd apps/console build
```

Expected: PASS.

- [ ] **Step 2: Find active Python AgentLens references**

Run:

```bash
rg -n "components/agentlens|python -m pytest|agentlens.event.v2|agentlens.waygent_projection|AgentLens backend" AGENTS.md CLAUDE.md README.md docs apps packages skills package.json
```

Expected: output lists active references to remove or rewrite.

- [ ] **Step 3: Delete Python tree**

Run:

```bash
rm -rf components/agentlens
```

Expected: `git status --short components/agentlens` shows deleted files only under `components/agentlens`.

- [ ] **Step 4: Rewrite active references**

For every non-historical active reference found in Step 2:

- replace `components/agentlens` active guidance with `packages/lens-store`, `packages/lens-projectors`, `apps/api`, and `apps/console`;
- replace `python -m pytest` active verification with Bun and console checks;
- leave migration documents unchanged when the paragraph clearly describes old repository migration history.

The active replacement text is:

```markdown
Active Lens work lives in `packages/lens-store`, `packages/lens-projectors`,
`apps/api`, and `apps/console`. The legacy Python AgentLens implementation was
removed and is not a supported Waygent runtime or inspection path.
```

- [ ] **Step 5: Verify no active references remain**

Run:

```bash
rg -n "components/agentlens|python -m pytest|agentlens.event.v2|agentlens.waygent_projection|AgentLens backend" AGENTS.md CLAUDE.md README.md docs apps packages skills package.json
```

Expected: no active instructions remain. Historical references in `docs/migration/` may remain only when they describe past migration context.

- [ ] **Step 6: Run deletion verification**

Run:

```bash
bun run check
bun run waygent:scenarios
bun run platform:demo
bun run --cwd apps/console build
git diff --check
```

Expected: PASS.

- [ ] **Step 7: Commit Python deletion**

Run:

```bash
git add -A -- . ':(exclude)**/.DS_Store'
git commit -m "chore: remove legacy Python AgentLens"
```

Expected: commit succeeds.

---

### Task 10: Full End-To-End Closure

**Files:**
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/operations/waygent.md`
- Modify: `docs/superpowers/plans/2026-05-22-waygent-lens-no-python-observability.md`

- [ ] **Step 1: Add closure note to architecture**

Append to `docs/architecture/waygent.md`:

```markdown
## No-Python Lens Observability

Waygent run inspection is TypeScript-first. `packages/lens-store` reads durable
run artifacts, `packages/lens-projectors` builds `waygent.run_inspection.v1`,
and CLI/API/console consume that shared projection. The legacy Python
AgentLens implementation has been removed from the active product path.
```

- [ ] **Step 2: Add operator note to operations docs**

Append to `docs/operations/waygent.md`:

```markdown
## Inspecting A Run

Use `waygent inspect --last` for structured JSON and `waygent explain --last`
for a short operator summary. The local API and console show the same
`waygent.run_inspection.v1` projection. Apply readiness is based on v2 state,
completion audit, artifact health, and reconciliation evidence; it is not
inferred from provider success.
```

- [ ] **Step 3: Mark plan complete**

In this plan file, add this line under the header after all implementation
tasks have passed:

```markdown
**Completion:** Implemented and verified with Bun, console build, platform demo,
scenario tests, and patch hygiene.
```

- [ ] **Step 4: Run final verification**

Run:

```bash
bun run check
bun run waygent:scenarios
bun run platform:demo
bun run --cwd apps/console build
git diff --check
git status --short --branch --untracked-files=all
```

Expected:

- all verification commands pass;
- status shows only intentional documentation changes before the final commit.

- [ ] **Step 5: Commit closure docs**

Run:

```bash
git add docs/architecture/waygent.md docs/operations/waygent.md docs/superpowers/plans/2026-05-22-waygent-lens-no-python-observability.md
git commit -m "docs: close no-python Lens observability migration"
```

Expected: commit succeeds.

## Final Verification Set

Run after Task 10:

```bash
bun run check
bun run waygent:scenarios
bun run platform:demo
bun run --cwd apps/console build
git diff --check
git status --short --branch --untracked-files=all
```

Expected:

- `bun run check`: PASS.
- `bun run waygent:scenarios`: PASS.
- `bun run platform:demo`: prints a JSON summary with `trust_status`.
- `bun run --cwd apps/console build`: PASS.
- `git diff --check`: no output.
- `git status --short --branch --untracked-files=all`: clean except branch ahead count.

## Self-Review Checklist

- Spec coverage:
  - TypeScript-only Lens path: Tasks 2-8.
  - API and console real-run visibility: Tasks 5-7.
  - CLI inspect/explain alignment: Task 8.
  - Python legacy deletion: Task 9.
  - Docs and final verification: Tasks 1 and 10.
- Placeholder scan: this plan contains concrete paths, commands, expected
  outputs, and code snippets for every implementation task.
- Type consistency:
  - Shared model name is `WaygentRunInspection`.
  - Shared schema string is `waygent.run_inspection.v1`.
  - Artifact health type is `WaygentArtifactHealth`.
  - API detail field is `inspection`.
  - Console inspection type is `ConsoleInspection`.
