# Waygent Recovery-Aware Orchestration And Apply Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make completed Waygent runs genuinely apply-ready by materializing verified checkpoint patch artifacts, validating them before completion, and routing recovery/apply failures through explicit barriers.

**Architecture:** Add a checkpoint artifact boundary inside `packages/orchestrator`, then make `runWaygent()`, `resumeRun()`, and `applyRun()` consume the same manifest-backed checkpoint contract. The first tasks close the current `completed -> apply_verified_checkpoint -> missing_verified_checkpoint` gap; subsequent tasks harden apply failure modes and extend the orchestration loop to continue safe waves until a real barrier appears.

**Tech Stack:** Bun 1.3+, TypeScript 5.9+, `bun:test`, Git patch/dry-run commands, filesystem artifacts via `@waygent/lens-store`, Waygent v2 run state, AgentLens event journal.

---

## Source Spec

- Design spec: `components/agentlens/docs/spec/2026-05-21-waygent-recovery-aware-orchestration-apply-pipeline-design.md`
- Related plan: `components/agentlens/docs/plan/2026-05-21-waygent-full-platform-implementation-program.md`

## Scope Boundary

This plan changes Waygent runtime behavior only. It does not revive KWS CPE/CME, add cloud execution, or let workers apply patches to the source checkout.

The minimum shipped result must prove:

- `runWaygent() -> resumeRun() -> applyRun()` succeeds for a verified fake-provider run;
- a run with missing checkpoint artifacts cannot be marked completed;
- `resumeRun()` offers `apply_verified_checkpoint` only when the checkpoint manifest and patch are resolvable;
- apply reports dirty checkout, missing artifact, digest mismatch, patch dry-run failure, and post-apply verification failure distinctly;
- safe-wave orchestration can continue to a dependent task once its dependency checkpoint exists.

## File Structure

Create:

- `packages/orchestrator/src/checkpointArtifacts.ts`
  Owns checkpoint manifests, patch creation, digest validation, and apply dry-run.
- `packages/orchestrator/src/completionAudit.ts`
  Owns completion audit construction and apply-readiness checks.
- `packages/orchestrator/tests/checkpointArtifacts.test.ts`
  Unit tests for checkpoint manifests, digest validation, dry-run, and failure classes.
- `packages/orchestrator/tests/orchestratorApplyE2E.test.ts`
  End-to-end tests for run, resume, and apply.

Modify:

- `packages/orchestrator/src/orchestrator.ts`
  Integrate checkpoint materialization, completion audit, and repeated safe-wave dispatch.
- `packages/orchestrator/src/runCommands.ts`
  Resolve manifests in apply, gate resume actions on real apply readiness, and record apply blockers.
- `packages/orchestrator/src/applyEngine.ts`
  Add dry-run and digest-aware apply support while preserving the existing patch-string helper behavior.
- `packages/orchestrator/src/recoveryExecutor.ts`
  Add checkpoint-specific recovery actions.
- `packages/orchestrator/src/index.ts`
  Export new helpers for tests and CLI consumers.
- `packages/orchestrator/tests/orchestratorRun.test.ts`
  Update expected events/checkpoints and add safe-wave continuation assertions.
- `packages/orchestrator/tests/orchestratorRunV2.test.ts`
  Strengthen completion audit expectations.
- `packages/orchestrator/tests/runCommandsV2.test.ts`
  Update apply/resume tests around manifest-backed checkpoints.
- `packages/orchestrator/tests/recoveryExecutor.test.ts`
  Cover checkpoint recovery choices.
- `tests/waygent-scenarios/*.json`
  Update golden replay event types and checkpoint refs.
- `packages/testkit/src/waygentScenarioHarness.ts`
  Normalize manifest-backed checkpoint refs.
- `skills/waygent/README.md` and `skills/waygent/SKILL.md`
  Document apply stop rules and checkpoint readiness.

## Execution Order

Run tasks sequentially. Tasks 1-5 touch shared runtime state and should not run in parallel. Task 6 may run after Task 3 if assigned to a separate worker, but only if that worker owns only scenario/docs files and reconciles expected events after runtime behavior lands.

---

### Task 1: Reproduce The Completed-But-Unappliable Gap

```yaml
id: T1
title: Reproduce completed run missing checkpoint artifact
owner_boundary: orchestrator tests only
files:
  - path: packages/orchestrator/tests/orchestratorApplyE2E.test.ts
    mode: owned
acceptance:
  - command: bun test packages/orchestrator/tests/orchestratorApplyE2E.test.ts
  - expected: FAIL before implementation because apply returns missing_verified_checkpoint after runWaygent completion
risks:
  - This test intentionally captures the current bug and must fail before Task 2.
```

**Files:**

- Create: `packages/orchestrator/tests/orchestratorApplyE2E.test.ts`

- [ ] **Step 1: Add the failing E2E test**

Create `packages/orchestrator/tests/orchestratorApplyE2E.test.ts`:

```ts
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runWaygent } from "../src/orchestrator";
import { applyRun, resumeRun } from "../src/runCommands";
import { readRunStateV2 } from "../src/runState";

function initSourceCheckout(): string {
  const workspace = mkdtempSync(join(tmpdir(), "waygent-apply-e2e-source-"));
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "before\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
  return workspace;
}

const plan = `
\`\`\`yaml waygent-task
id: task_apply_ready
title: Update README through fake provider
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - test -f README.md
\`\`\`
`;

describe("Waygent run to apply E2E", () => {
  test("a completed run exposes and applies a real verified checkpoint", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-apply-e2e-root-"));
    const workspace = initSourceCheckout();

    await runWaygent({
      root,
      workspace,
      run_id: "run_apply_ready",
      plan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_apply_ready");
    expect(state.status).toBe("completed");
    expect(resumeRun({ root, run: "run_apply_ready", dry_run: true }).allowed_actions).toContain(
      "apply_verified_checkpoint"
    );
    expect(await applyRun({ root, run: "run_apply_ready", workspace })).toMatchObject({
      command: "apply",
      run_id: "run_apply_ready",
      status: "applied"
    });
  });
});
```

- [ ] **Step 2: Run the focused test and confirm the failure**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorApplyE2E.test.ts
```

Expected before Task 2:

```text
FAIL Waygent run to apply E2E > a completed run exposes and applies a real verified checkpoint
Expected status "applied" but received "blocked" with reason "missing_verified_checkpoint"
```

- [ ] **Step 3: Commit the failing test**

```bash
git add packages/orchestrator/tests/orchestratorApplyE2E.test.ts
git commit -m "test: reproduce Waygent missing checkpoint apply gap"
```

---

### Task 2: Add Manifest-Backed Checkpoint Artifacts

```yaml
id: T2
title: Add checkpoint artifact helper
owner_boundary: checkpoint artifact helper and tests
files:
  - path: packages/orchestrator/src/checkpointArtifacts.ts
    mode: owned
  - path: packages/orchestrator/tests/checkpointArtifacts.test.ts
    mode: owned
  - path: packages/orchestrator/src/index.ts
    mode: edit
acceptance:
  - command: bun test packages/orchestrator/tests/checkpointArtifacts.test.ts
  - expected: PASS
risks:
  - Git patch generation must run in isolated temp checkouts in tests.
```

**Files:**

- Create: `packages/orchestrator/src/checkpointArtifacts.ts`
- Create: `packages/orchestrator/tests/checkpointArtifacts.test.ts`
- Modify: `packages/orchestrator/src/index.ts`

- [ ] **Step 1: Write checkpoint helper tests**

Create `packages/orchestrator/tests/checkpointArtifacts.test.ts`:

```ts
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import {
  createCheckpointArtifact,
  dryRunCheckpointPatch,
  readCheckpointManifest,
  resolveCheckpointPatch,
  validateCheckpointManifest
} from "../src/checkpointArtifacts";

function initRepo(prefix: string): string {
  const repo = mkdtempSync(join(tmpdir(), prefix));
  Bun.spawnSync(["git", "init", "-q"], { cwd: repo });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: repo });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: repo });
  writeFileSync(join(repo, "README.md"), "before\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: repo });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: repo });
  return repo;
}

function cloneWorktree(source: string, prefix: string): string {
  const worktree = mkdtempSync(join(tmpdir(), prefix));
  Bun.spawnSync(["git", "clone", "--quiet", source, worktree]);
  return worktree;
}

describe("checkpoint artifacts", () => {
  test("creates a manifest and patch for a changed worktree", () => {
    const runRoot = mkdtempSync(join(tmpdir(), "waygent-checkpoint-run-"));
    const source = initRepo("waygent-checkpoint-source-");
    const worktree = cloneWorktree(source, "waygent-checkpoint-worktree-");
    writeFileSync(join(worktree, "README.md"), "after\n");

    const checkpoint = createCheckpointArtifact({
      run_root: runRoot,
      run_id: "run_checkpoint",
      task_id: "task_checkpoint",
      candidate_id: "candidate_checkpoint",
      worktree_path: worktree,
      changed_files: ["README.md"],
      verification_refs: ["artifacts/kernel/verify_task_checkpoint_1.json"]
    });

    expect(checkpoint.status).toBe("created");
    expect(checkpoint.manifest_ref).toBe("artifacts/checkpoints/task_checkpoint/candidate_checkpoint.json");
    expect(existsSync(join(runRoot, checkpoint.manifest_ref))).toBe(true);
    expect(existsSync(join(runRoot, checkpoint.patch_ref))).toBe(true);
    expect(readFileSync(join(runRoot, checkpoint.patch_ref), "utf8")).toContain("+after");
    expect(validateCheckpointManifest(runRoot, checkpoint.manifest_ref)).toMatchObject({
      ok: true,
      patch_ref: checkpoint.patch_ref
    });
    expect(resolveCheckpointPatch(runRoot, checkpoint.manifest_ref)?.patch).toContain("+after");
    expect(dryRunCheckpointPatch({
      run_root: runRoot,
      checkpoint_ref: checkpoint.manifest_ref,
      source
    })).toMatchObject({ status: "passed" });
  });

  test("reports digest mismatch without throwing", () => {
    const runRoot = mkdtempSync(join(tmpdir(), "waygent-checkpoint-mismatch-"));
    const source = initRepo("waygent-checkpoint-mismatch-source-");
    const worktree = cloneWorktree(source, "waygent-checkpoint-mismatch-worktree-");
    writeFileSync(join(worktree, "README.md"), "after\n");

    const checkpoint = createCheckpointArtifact({
      run_root: runRoot,
      run_id: "run_mismatch",
      task_id: "task_mismatch",
      candidate_id: "candidate_mismatch",
      worktree_path: worktree,
      changed_files: ["README.md"],
      verification_refs: []
    });
    writeFileSync(join(runRoot, checkpoint.patch_ref), "corrupted\n");

    expect(validateCheckpointManifest(runRoot, checkpoint.manifest_ref)).toMatchObject({
      ok: false,
      reason: "checkpoint_digest_mismatch"
    });
  });

  test("reads existing checkpoint manifests", () => {
    const runRoot = mkdtempSync(join(tmpdir(), "waygent-checkpoint-read-"));
    const source = initRepo("waygent-checkpoint-read-source-");
    const worktree = cloneWorktree(source, "waygent-checkpoint-read-worktree-");
    writeFileSync(join(worktree, "README.md"), "after\n");
    const checkpoint = createCheckpointArtifact({
      run_root: runRoot,
      run_id: "run_read",
      task_id: "task_read",
      candidate_id: "candidate_read",
      worktree_path: worktree,
      changed_files: ["README.md"],
      verification_refs: []
    });

    expect(readCheckpointManifest(runRoot, checkpoint.manifest_ref)).toMatchObject({
      schema: "waygent.checkpoint_manifest.v1",
      task_id: "task_read",
      candidate_id: "candidate_read"
    });
  });
});
```

- [ ] **Step 2: Run the tests and verify missing module failure**

Run:

```bash
bun test packages/orchestrator/tests/checkpointArtifacts.test.ts
```

Expected before implementation:

```text
Cannot find module '../src/checkpointArtifacts'
```

- [ ] **Step 3: Implement checkpoint artifact helpers**

Create `packages/orchestrator/src/checkpointArtifacts.ts`:

```ts
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { sha256, writeArtifact } from "@waygent/lens-store";

export interface CheckpointManifest {
  schema: "waygent.checkpoint_manifest.v1";
  run_id: string;
  task_id: string;
  candidate_id: string;
  patch_ref: string;
  patch_sha256: string;
  patch_byte_length: number;
  changed_files: string[];
  source_base: string | null;
  worktree_path: string;
  verification_refs: string[];
  created_at: string;
  dry_run_status: "not_run" | "passed" | "failed";
  dry_run_evidence_ref: string | null;
}

export interface CreateCheckpointArtifactInput {
  run_root: string;
  run_id: string;
  task_id: string;
  candidate_id: string;
  worktree_path: string;
  changed_files: string[];
  verification_refs: string[];
}

export interface CreatedCheckpointArtifact {
  status: "created";
  manifest_ref: string;
  patch_ref: string;
  patch_sha256: string;
  patch_byte_length: number;
}

export interface CheckpointValidationResult {
  ok: boolean;
  patch_ref?: string;
  reason?: "checkpoint_manifest_missing" | "checkpoint_patch_missing" | "checkpoint_digest_mismatch";
}

export interface CheckpointDryRunResult {
  status: "passed" | "failed";
  reason?: "checkpoint_unresolvable" | "patch_dry_run_failed";
  evidence_ref: string;
}

export function createCheckpointArtifact(input: CreateCheckpointArtifactInput): CreatedCheckpointArtifact {
  const diff = spawnSync("git", ["diff", "--binary"], {
    cwd: input.worktree_path,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (diff.status !== 0) {
    throw new Error(`failed to create checkpoint diff for ${input.task_id}: ${diff.stderr}`);
  }
  const patch = diff.stdout;
  const patchArtifact = writeArtifact(
    input.run_root,
    `checkpoints/${input.task_id}/${input.candidate_id}.patch`,
    patch,
    "text/x-diff"
  );
  const manifest: CheckpointManifest = {
    schema: "waygent.checkpoint_manifest.v1",
    run_id: input.run_id,
    task_id: input.task_id,
    candidate_id: input.candidate_id,
    patch_ref: patchArtifact.path,
    patch_sha256: patchArtifact.sha256,
    patch_byte_length: patchArtifact.byte_length,
    changed_files: input.changed_files,
    source_base: currentHead(input.worktree_path),
    worktree_path: input.worktree_path,
    verification_refs: input.verification_refs,
    created_at: new Date().toISOString(),
    dry_run_status: "not_run",
    dry_run_evidence_ref: null
  };
  const manifestArtifact = writeArtifact(
    input.run_root,
    `checkpoints/${input.task_id}/${input.candidate_id}.json`,
    `${JSON.stringify(manifest, null, 2)}\n`
  );
  return {
    status: "created",
    manifest_ref: manifestArtifact.path,
    patch_ref: patchArtifact.path,
    patch_sha256: patchArtifact.sha256,
    patch_byte_length: patchArtifact.byte_length
  };
}

export function readCheckpointManifest(runRoot: string, checkpointRef: string): CheckpointManifest {
  const path = resolveRunArtifactPath(runRoot, checkpointRef);
  return JSON.parse(readFileSync(path, "utf8")) as CheckpointManifest;
}

export function validateCheckpointManifest(runRoot: string, checkpointRef: string): CheckpointValidationResult {
  const manifestPath = resolveRunArtifactPath(runRoot, checkpointRef);
  if (!existsSync(manifestPath)) return { ok: false, reason: "checkpoint_manifest_missing" };
  const manifest = readCheckpointManifest(runRoot, checkpointRef);
  const patchPath = resolveRunArtifactPath(runRoot, manifest.patch_ref);
  if (!existsSync(patchPath)) return { ok: false, reason: "checkpoint_patch_missing" };
  const patch = readFileSync(patchPath);
  if (sha256(patch) !== manifest.patch_sha256 || patch.byteLength !== manifest.patch_byte_length) {
    return { ok: false, reason: "checkpoint_digest_mismatch" };
  }
  return { ok: true, patch_ref: manifest.patch_ref };
}

export function resolveCheckpointPatch(runRoot: string, checkpointRef: string): { manifest: CheckpointManifest; patch: string } | null {
  const validation = validateCheckpointManifest(runRoot, checkpointRef);
  if (!validation.ok) return null;
  const manifest = readCheckpointManifest(runRoot, checkpointRef);
  return {
    manifest,
    patch: readFileSync(resolveRunArtifactPath(runRoot, manifest.patch_ref), "utf8")
  };
}

export function dryRunCheckpointPatch(input: { run_root: string; checkpoint_ref: string; source: string }): CheckpointDryRunResult {
  const resolved = resolveCheckpointPatch(input.run_root, input.checkpoint_ref);
  if (!resolved) {
    const evidence = writeArtifact(input.run_root, `checkpoints/dry-run-${Date.now()}.json`, `${JSON.stringify({
      checkpoint_ref: input.checkpoint_ref,
      status: "failed",
      reason: "checkpoint_unresolvable"
    }, null, 2)}\n`);
    return { status: "failed", reason: "checkpoint_unresolvable", evidence_ref: evidence.path };
  }
  const patchPath = join(input.source, ".waygent-dry-run.patch");
  writeFileSync(patchPath, resolved.patch);
  const dryRun = spawnSync("git", ["apply", "--check", patchPath], {
    cwd: input.source,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  rmSync(patchPath, { force: true });
  const status = dryRun.status === 0 ? "passed" : "failed";
  const evidence = writeArtifact(input.run_root, `checkpoints/dry-run-${Date.now()}.json`, `${JSON.stringify({
    checkpoint_ref: input.checkpoint_ref,
    status,
    stdout: dryRun.stdout,
    stderr: dryRun.stderr
  }, null, 2)}\n`);
  return {
    status,
    ...(status === "failed" ? { reason: "patch_dry_run_failed" as const } : {}),
    evidence_ref: evidence.path
  };
}

export function resolveRunArtifactPath(runRoot: string, ref: string): string {
  return ref.startsWith("/") ? ref : join(runRoot, ref);
}

function currentHead(worktree: string): string | null {
  const head = spawnSync("git", ["rev-parse", "HEAD"], {
    cwd: worktree,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"]
  });
  return head.status === 0 ? head.stdout.trim() : null;
}
```

- [ ] **Step 4: Export the helper**

Modify `packages/orchestrator/src/index.ts` and add:

```ts
export * from "./checkpointArtifacts";
```

- [ ] **Step 5: Run the helper tests**

Run:

```bash
bun test packages/orchestrator/tests/checkpointArtifacts.test.ts
```

Expected:

```text
3 pass
0 fail
```

- [ ] **Step 6: Commit Task 2**

```bash
git add packages/orchestrator/src/checkpointArtifacts.ts packages/orchestrator/src/index.ts packages/orchestrator/tests/checkpointArtifacts.test.ts
git commit -m "feat: add Waygent checkpoint artifacts"
```

---

### Task 3: Make Run Completion Depend On Apply-Ready Checkpoints

```yaml
id: T3
title: Gate completion on checkpoint artifacts
owner_boundary: orchestrator run lifecycle and completion audit
files:
  - path: packages/orchestrator/src/completionAudit.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: edit
  - path: packages/orchestrator/src/index.ts
    mode: edit
  - path: packages/orchestrator/tests/orchestratorRunV2.test.ts
    mode: edit
  - path: packages/orchestrator/tests/orchestratorApplyE2E.test.ts
    mode: edit
acceptance:
  - command: bun test packages/orchestrator/tests/orchestratorApplyE2E.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts
  - expected: PASS
risks:
  - Existing event-count tests will need updates once checkpoint events are emitted.
```

**Files:**

- Create: `packages/orchestrator/src/completionAudit.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Modify: `packages/orchestrator/tests/orchestratorRunV2.test.ts`
- Modify: `packages/orchestrator/tests/orchestratorApplyE2E.test.ts`

- [ ] **Step 1: Add completion audit helper tests to the E2E file**

Append this test to `packages/orchestrator/tests/orchestratorApplyE2E.test.ts`:

```ts
test("a run with no checkpoint artifact is blocked before completion", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-no-checkpoint-root-"));
  const workspace = initSourceCheckout();
  const noWritePlan = `
\`\`\`yaml waygent-task
id: task_no_checkpoint
title: No checkpoint task
dependencies: []
file_claims:
  - path: README.md
    mode: read_only
risk: low
verify:
  - test -f README.md
\`\`\`
`;

  await runWaygent({
    root,
    workspace,
    run_id: "run_no_checkpoint",
    plan: noWritePlan,
    profile: { provider: "fake", execution_mode: "multi-agent" }
  });

  const state = readRunStateV2(root, "run_no_checkpoint");
  expect(state.status).toBe("blocked");
  expect(state.lifecycle_outcome).toBe("blocked");
  expect(state.completion_audit).toMatchObject({ status: "failed" });
  expect(resumeRun({ root, run: "run_no_checkpoint", dry_run: true }).allowed_actions).not.toContain(
    "apply_verified_checkpoint"
  );
});
```

- [ ] **Step 2: Run E2E tests and confirm the new blocked-run test fails**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorApplyE2E.test.ts
```

Expected before implementation:

```text
FAIL because run_no_checkpoint is still marked completed
```

- [ ] **Step 3: Implement completion audit helper**

Create `packages/orchestrator/src/completionAudit.ts`:

```ts
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { validateCheckpointManifest } from "./checkpointArtifacts";

export interface CompletionAuditInput {
  state: WaygentRunStateV2;
  required_checks: string[];
  verification_evidence: Array<Record<string, unknown>>;
  review_evidence: Array<Record<string, unknown>>;
  prompt_to_artifact_checklist: string[];
}

export function buildCompletionAudit(input: CompletionAuditInput): Record<string, unknown> {
  const checkpointResults = Object.values(input.state.tasks)
    .filter((task) => task.status === "verified")
    .flatMap((task) => {
      if (task.checkpoint_refs.length === 0) {
        return [{ task_id: task.id, ok: false, reason: "missing_checkpoint" }];
      }
      return task.checkpoint_refs.map((ref) => ({
        task_id: task.id,
        checkpoint_ref: ref,
        ...validateCheckpointManifest(input.state.run_root, ref)
      }));
    });
  const failedCheckpoints = checkpointResults.filter((result) => !result.ok);
  const passed = failedCheckpoints.length === 0 && checkpointResults.length > 0;
  return {
    status: passed ? "passed" : "failed",
    required_checks: input.required_checks,
    verification_evidence: input.verification_evidence,
    review_evidence: input.review_evidence,
    checkpoint_evidence: checkpointResults,
    state_reconciliation: { passed: false },
    prompt_to_artifact_checklist: input.prompt_to_artifact_checklist,
    residual_risk: failedCheckpoints.map((result) => `${result.task_id}:${result.reason}`)
  };
}

export function hasApplyReadyCheckpoint(state: WaygentRunStateV2): boolean {
  if ((state.completion_audit as { status?: string } | null)?.status !== "passed") return false;
  return Object.values(state.tasks)
    .filter((task) => task.status === "verified")
    .every((task) =>
      task.checkpoint_refs.some((ref) => validateCheckpointManifest(state.run_root, ref).ok)
    );
}
```

- [ ] **Step 4: Export completion audit helper**

Modify `packages/orchestrator/src/index.ts` and add:

```ts
export * from "./completionAudit";
```

- [ ] **Step 5: Integrate checkpoint creation in `runWaygent()`**

In `packages/orchestrator/src/orchestrator.ts`, add imports:

```ts
import { spawnSync } from "node:child_process";
import { buildCompletionAudit } from "./completionAudit";
import { createCheckpointArtifact, dryRunCheckpointPatch } from "./checkpointArtifacts";
```

Before provider execution, replace `mkdirSync(taskWorktree.path, { recursive:
true })` with a real source-based worktree:

```ts
mkdirSync(dirname(taskWorktree.path), { recursive: true });
const addWorktree = spawnSync("git", ["worktree", "add", "--detach", taskWorktree.path, "HEAD"], {
  cwd: workspace,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "pipe"]
});
if (addWorktree.status !== 0) {
  throw new Error(`failed to create task worktree for ${task.id}: ${addWorktree.stderr}`);
}
```

In the verification success block, replace the logical checkpoint assignment:

```ts
const verified = mergeCandidate({ task_id: task.id, candidate_id: worker.candidate_id, reviewed: true, verified: true });
task.checkpoint_ref = verified.checkpoint_ref ?? `checkpoint_${task.id}_${worker.candidate_id}`;
checkpointRefs.set(task.id, task.checkpoint_ref);
```

with manifest-backed checkpoint creation:

```ts
const verified = mergeCandidate({ task_id: task.id, candidate_id: worker.candidate_id, reviewed: true, verified: true });
const hasWritableClaims = parsedTask.file_claims.some((claim) => claim.mode !== "read_only");
if (verified.merged && hasWritableClaims) {
  const checkpoint = createCheckpointArtifact({
    run_root: paths.root,
    run_id: runId,
    task_id: task.id,
    candidate_id: worker.candidate_id,
    worktree_path: taskWorktree.path,
    changed_files: worker.changed_files,
    verification_refs: taskVerificationRecords.map((record) => String(record.kernel_result_ref))
  });
  const dryRun = dryRunCheckpointPatch({
    run_root: paths.root,
    checkpoint_ref: checkpoint.manifest_ref,
    source: workspace
  });
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: sequence++,
    event_type: "runway.checkpoint_created",
    phase: "checkpoint",
    outcome: "success",
    summary: "Verified checkpoint artifact created.",
    payload: {
      task_id: task.id,
      candidate_id: worker.candidate_id,
      checkpoint_ref: checkpoint.manifest_ref,
      patch_ref: checkpoint.patch_ref
    }
  }));
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: sequence++,
    event_type: "runway.apply_dry_run_result",
    phase: "checkpoint",
    outcome: dryRun.status === "passed" ? "success" : "blocked",
    summary: dryRun.status === "passed" ? "Checkpoint patch dry-run passed." : "Checkpoint patch dry-run failed.",
    payload: { task_id: task.id, checkpoint_ref: checkpoint.manifest_ref, dry_run: dryRun }
  }));
  if (dryRun.status === "passed") {
    task.checkpoint_ref = checkpoint.manifest_ref;
    checkpointRefs.set(task.id, checkpoint.manifest_ref);
  }
}
```

- [ ] **Step 6: Use completion audit helper in `runWaygent()`**

Replace the completion audit object in `packages/orchestrator/src/orchestrator.ts` with:

```ts
const audit = buildCompletionAudit({
  state,
  required_checks: safeWave.flatMap((taskId) => verificationCommands.get(taskId) ?? []),
  verification_evidence: verificationRecords,
  review_evidence: [],
  prompt_to_artifact_checklist: [
    "task_packet_written",
    "provider_attempt_recorded",
    "kernel_verification_recorded",
    "checkpoint_artifact_recorded"
  ]
});
state.completion_audit = audit;
state.status = audit.status === "passed" ? "completed" : "blocked";
state.lifecycle_outcome = audit.status === "passed" ? "finished" : "blocked";
```

Keep reconciliation after this block and preserve its ability to turn the run
back to `blocked` when state drift exists.

- [ ] **Step 7: Strengthen v2 run-state assertions**

In `packages/orchestrator/tests/orchestratorRunV2.test.ts`, add:

```ts
expect(state.tasks.task_a?.checkpoint_refs[0]).toContain("artifacts/checkpoints/task_a/candidate_task_a.json");
expect(state.completion_audit).toMatchObject({
  status: "passed",
  checkpoint_evidence: [expect.objectContaining({ ok: true })]
});
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
bun test packages/orchestrator/tests/checkpointArtifacts.test.ts packages/orchestrator/tests/orchestratorApplyE2E.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts
```

Expected:

```text
all tests pass
```

- [ ] **Step 9: Commit Task 3**

```bash
git add packages/orchestrator/src/checkpointArtifacts.ts packages/orchestrator/src/completionAudit.ts packages/orchestrator/src/index.ts packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/orchestratorApplyE2E.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts
git commit -m "feat: require checkpoint artifacts before Waygent completion"
```

---

### Task 4: Make Resume And Apply Consume Checkpoint Manifests

```yaml
id: T4
title: Align resume and apply with checkpoint manifests
owner_boundary: run commands and apply engine
files:
  - path: packages/orchestrator/src/runCommands.ts
    mode: edit
  - path: packages/orchestrator/src/applyEngine.ts
    mode: edit
  - path: packages/orchestrator/src/recoveryExecutor.ts
    mode: edit
  - path: packages/orchestrator/tests/runCommandsV2.test.ts
    mode: edit
  - path: packages/orchestrator/tests/applyEngine.test.ts
    mode: edit
  - path: packages/orchestrator/tests/recoveryExecutor.test.ts
    mode: edit
acceptance:
  - command: bun test packages/orchestrator/tests/runCommandsV2.test.ts packages/orchestrator/tests/applyEngine.test.ts packages/orchestrator/tests/recoveryExecutor.test.ts
  - expected: PASS
risks:
  - Keep dirty checkout stop rule strict; do not auto-retry apply.
```

**Files:**

- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/orchestrator/src/applyEngine.ts`
- Modify: `packages/orchestrator/src/recoveryExecutor.ts`
- Modify: `packages/orchestrator/tests/runCommandsV2.test.ts`
- Modify: `packages/orchestrator/tests/applyEngine.test.ts`
- Modify: `packages/orchestrator/tests/recoveryExecutor.test.ts`

- [ ] **Step 1: Add apply engine tests for dry-run and post-apply failure**

Append to `packages/orchestrator/tests/applyEngine.test.ts`:

```ts
test("reports patch dry-run failure before mutation", async () => {
  const source = mkdtempSync(join(tmpdir(), "waygent-apply-dry-run-source-"));
  Bun.spawnSync(["git", "init", "-q"], { cwd: source });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: source });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: source });
  writeFileSync(join(source, "README.md"), "different\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: source });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: source });

  const patch = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-before\n+after\n";
  expect(await applyVerifiedCheckpoint({ source, patch, post_apply_commands: ["grep after README.md"] })).toMatchObject({
    status: "blocked",
    reason: "patch_dry_run_failed"
  });
});

test("reports post-apply verification failure", async () => {
  const source = mkdtempSync(join(tmpdir(), "waygent-post-apply-source-"));
  Bun.spawnSync(["git", "init", "-q"], { cwd: source });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: source });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: source });
  writeFileSync(join(source, "README.md"), "before\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: source });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: source });

  const patch = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-before\n+after\n";
  expect(await applyVerifiedCheckpoint({ source, patch, post_apply_commands: ["grep missing README.md"] })).toMatchObject({
    status: "failed",
    reason: "post_apply_verification_failed"
  });
});
```

- [ ] **Step 2: Update apply engine with dry-run**

In `packages/orchestrator/src/applyEngine.ts`, run `git apply --check` before
writing the mutation:

```ts
const patchPath = join(input.source, ".waygent-apply.patch");
writeFileSync(patchPath, input.patch);
const dryRun = spawnSync("git", ["apply", "--check", patchPath], { cwd: input.source, encoding: "utf8" });
if (dryRun.status !== 0) {
  rmSync(patchPath, { force: true });
  return { status: "blocked", reason: "patch_dry_run_failed" };
}
const apply = spawnSync("git", ["apply", patchPath], { cwd: input.source, encoding: "utf8" });
rmSync(patchPath, { force: true });
```

- [ ] **Step 3: Gate resume on apply-ready checkpoint evidence**

In `packages/orchestrator/src/runCommands.ts`, import:

```ts
import { hasApplyReadyCheckpoint } from "./completionAudit";
```

Then replace the completed v2 state resume branch with:

```ts
if (v2State.status === "completed") {
  return {
    run_id: explanation.run_id,
    allowed_actions: hasApplyReadyCheckpoint(v2State)
      ? ["inspect_run", "apply_verified_checkpoint"]
      : ["inspect_run", "retry_checkpoint_generation", "human_decision"],
    dry_run: options.dry_run ?? false
  };
}
```

- [ ] **Step 4: Resolve checkpoint manifests in apply**

In `packages/orchestrator/src/runCommands.ts`, import:

```ts
import { resolveCheckpointPatch, validateCheckpointManifest } from "./checkpointArtifacts";
```

Replace the v2 checkpoint path resolution with:

```ts
const checkpointRef = v2State.apply.checkpoint_ref ?? Object.values(v2State.tasks).flatMap((task) => task.checkpoint_refs)[0];
const validation = checkpointRef ? validateCheckpointManifest(v2State.run_root, checkpointRef) : { ok: false, reason: "missing_verified_checkpoint" };
if (!checkpointRef || !validation.ok) {
  const reason = validation.reason ?? "missing_verified_checkpoint";
  appendEvent(paths.events, nextRunEvent(paths.events, {
    run_id: runId,
    event_type: "runway.apply_blocked",
    phase: "apply",
    outcome: "blocked",
    summary: "Apply blocked because no verified checkpoint is available.",
    payload: { reason },
    trust_impact: "requires_review"
  }));
  writeRunStateV2(options.root, { ...v2State, apply: { status: "blocked", reason } });
  return { command: "apply", run_id: runId, status: "blocked", reason };
}
const resolved = resolveCheckpointPatch(v2State.run_root, checkpointRef);
if (!resolved) {
  writeRunStateV2(options.root, { ...v2State, apply: { status: "blocked", reason: "missing_verified_checkpoint" } });
  return { command: "apply", run_id: runId, status: "blocked", reason: "missing_verified_checkpoint" };
}
const patch = resolved.patch;
```

- [ ] **Step 5: Add checkpoint recovery action tests**

In `packages/orchestrator/tests/recoveryExecutor.test.ts`, add:

```ts
expect(selectResumeAction({ failure_class: "missing_checkpoint", retry_count: 0, max_retries: 1, checkpoint_ref: null })).toEqual({
  action: "retry_checkpoint_generation",
  automatic: true
});
expect(selectResumeAction({ failure_class: "artifact_missing", retry_count: 1, max_retries: 1, checkpoint_ref: null })).toEqual({
  action: "human_decision",
  automatic: false
});
```

- [ ] **Step 6: Extend recovery action type and selection**

In `packages/orchestrator/src/recoveryExecutor.ts`, update the action union:

```ts
action:
  | "retry_same_provider"
  | "retry_switch_provider"
  | "rerun_verification"
  | "retry_checkpoint_generation"
  | "clean_source_checkout"
  | "human_decision";
```

Add before the default branch:

```ts
if (input.failure_class === "missing_checkpoint" || input.failure_class === "artifact_missing" || input.failure_class === "state_drift") {
  return input.retry_count < input.max_retries
    ? { action: "retry_checkpoint_generation", automatic: true }
    : { action: "human_decision", automatic: false };
}
if (input.failure_class === "dirty_source_checkout" || input.failure_class === "needs_rebase") {
  return { action: "clean_source_checkout", automatic: false };
}
```

- [ ] **Step 7: Update run command tests**

In `packages/orchestrator/tests/runCommandsV2.test.ts`, keep the existing
manual patch-path test, then add a manifest-backed test by creating a manifest
with `createCheckpointArtifact()` and asserting:

```ts
expect(resumeRun({ root, run: "run_apply", dry_run: true }).allowed_actions).toContain("apply_verified_checkpoint");
expect(await applyRun({ root, run: "run_apply", workspace })).toMatchObject({
  command: "apply",
  run_id: "run_apply",
  status: "applied"
});
```

Also update the missing checkpoint test to expect:

```ts
expect(resumeRun({ root, run: "run_missing", dry_run: true }).allowed_actions).toEqual([
  "inspect_run",
  "retry_checkpoint_generation",
  "human_decision"
]);
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
bun test packages/orchestrator/tests/runCommandsV2.test.ts packages/orchestrator/tests/applyEngine.test.ts packages/orchestrator/tests/recoveryExecutor.test.ts packages/orchestrator/tests/orchestratorApplyE2E.test.ts
```

Expected:

```text
all tests pass
```

- [ ] **Step 9: Commit Task 4**

```bash
git add packages/orchestrator/src/runCommands.ts packages/orchestrator/src/applyEngine.ts packages/orchestrator/src/recoveryExecutor.ts packages/orchestrator/tests/runCommandsV2.test.ts packages/orchestrator/tests/applyEngine.test.ts packages/orchestrator/tests/recoveryExecutor.test.ts packages/orchestrator/tests/orchestratorApplyE2E.test.ts
git commit -m "fix: align Waygent resume and apply checkpoints"
```

---

### Task 5: Continue Safe Waves Through Dependency Checkpoints

```yaml
id: T5
title: Repeat orchestration safe waves until blocked or complete
owner_boundary: orchestrator loop and scheduler integration
files:
  - path: packages/orchestrator/src/orchestrator.ts
    mode: edit
  - path: packages/orchestrator/tests/orchestratorRun.test.ts
    mode: edit
acceptance:
  - command: bun test packages/orchestrator/tests/orchestratorRun.test.ts packages/runway-control/tests/barriers.test.ts
  - expected: PASS
risks:
  - Keep this as a small loop over parsed tasks; do not rewrite the scheduler package.
```

**Files:**

- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/tests/orchestratorRun.test.ts`

- [ ] **Step 1: Add dependent-task continuation test**

Append to `packages/orchestrator/tests/orchestratorRun.test.ts`:

```ts
test("continues to dependent tasks after dependency checkpoint exists", async () => {
  const root = mkdtempSync(join(tmpdir(), "waygent-dependent-wave-"));
  const result = await runWaygent({
    root,
    run_id: "run_dependent_wave",
    profile: { provider: "fake", execution_mode: "multi-agent" },
    plan: `
\`\`\`yaml waygent-task
id: task_base
title: Base task
dependencies: []
file_claims:
  - path: base.txt
    mode: owned
risk: low
verify:
  - test -f base.txt
\`\`\`
\`\`\`yaml waygent-task
id: task_followup
title: Followup task
dependencies: [task_base]
file_claims:
  - path: followup.txt
    mode: owned
risk: low
verify:
  - test -f followup.txt
\`\`\`
`
  });

  expect(result.events.filter((event) => event.event_type === "runway.worker_result")).toHaveLength(2);
  expect(readRunStateV2(root, "run_dependent_wave").tasks.task_followup?.status).toBe("verified");
});
```

- [ ] **Step 2: Run the test and confirm only the first safe wave runs**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorRun.test.ts
```

Expected before implementation:

```text
FAIL because task_followup remains pending and only one worker_result event exists
```

- [ ] **Step 3: Refactor `runWaygent()` to recompute safe waves**

In `packages/orchestrator/src/orchestrator.ts`, replace the single `safeWave`
loop with a loop that:

```ts
let waveIndex = 1;
while (true) {
  const projection = buildDurableProjection(graph);
  const safeWave = projection.safe_wave;
  if (safeWave.length === 0) break;
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: sequence++,
    event_type: "runway.safe_wave_selected",
    phase: "schedule",
    outcome: "success",
    summary: "Safe wave selected.",
    payload: { safe_wave: safeWave, wave_id: `wave_${waveIndex}` }
  }));
  updateRunStateV2(options.root, runId, (state) => {
    state.safe_waves.push({ wave_id: `wave_${waveIndex}`, ready: safeWave, withheld: projection.withheld_tasks });
  });
  for (const taskId of safeWave) {
    await runOneTask(taskId);
    const completedTask = graph.tasks.get(taskId);
    if (completedTask?.checkpoint_ref) completedTask.status = "APPLIED";
  }
  waveIndex += 1;
}
```

Extract the current per-task body into an inner `async function runOneTask(taskId:
string): Promise<void>` inside `runWaygent()` so the first implementation stays
local to `orchestrator.ts`.

- [ ] **Step 4: Preserve existing safe-wave tests**

Update expected event lists in `packages/orchestrator/tests/orchestratorRun.test.ts`
to include `runway.checkpoint_created` and `runway.apply_dry_run_result` after
each successful verification.
For the original single-task test, expect:

```ts
expect(result.events.map((event) => event.event_type)).toContain("runway.checkpoint_created");
expect(result.events.map((event) => event.event_type)).toContain("runway.apply_dry_run_result");
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorRun.test.ts packages/orchestrator/tests/orchestratorApplyE2E.test.ts packages/runway-control/tests/barriers.test.ts
```

Expected:

```text
all tests pass
```

- [ ] **Step 6: Commit Task 5**

```bash
git add packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/orchestratorRun.test.ts
git commit -m "feat: continue Waygent safe waves through checkpoints"
```

---

### Task 6: Update Scenarios, Skill Docs, And Final Verification

```yaml
id: T6
title: Update golden scenarios and operator docs
owner_boundary: testkit, scenarios, skill docs, final verification
files:
  - path: tests/waygent-scenarios
    mode: edit
  - path: packages/testkit/src/waygentScenarioHarness.ts
    mode: edit
  - path: skills/waygent/SKILL.md
    mode: edit
  - path: skills/waygent/README.md
    mode: edit
acceptance:
  - command: bun run waygent:scenarios
  - expected: PASS
  - command: skills/waygent/evals/run.sh
  - expected: PASS
  - command: bun run check
  - expected: PASS
  - command: git diff --check
  - expected: no output
risks:
  - Scenario event counts must reflect real emitted events after Tasks 3-5.
```

**Files:**

- Modify: `packages/testkit/src/waygentScenarioHarness.ts`
- Modify: `tests/waygent-scenarios/dirty-apply-block.json`
- Modify: `tests/waygent-scenarios/missing-checkpoint.json`
- Modify: `tests/waygent-scenarios/overlapping-claims.json`
- Modify: `tests/waygent-scenarios/trivial-success.json`
- Modify: `tests/waygent-scenarios/malformed-provider.json`
- Modify: `skills/waygent/SKILL.md`
- Modify: `skills/waygent/README.md`

- [ ] **Step 1: Update scenario checkpoint normalization**

In `packages/testkit/src/waygentScenarioHarness.ts`, replace `checkpointRefs()`
with:

```ts
function checkpointRefs(payload: Record<string, unknown> | undefined): string[] {
  if (!payload) return [];
  const direct = typeof payload.checkpoint_ref === "string" ? [payload.checkpoint_ref] : [];
  const patch = typeof payload.patch_ref === "string" ? [payload.patch_ref] : [];
  const worker = payload.worker && typeof payload.worker === "object" ? payload.worker as Record<string, unknown> : undefined;
  const workerCheckpoint = worker && typeof worker.checkpoint_ref === "string" ? [worker.checkpoint_ref] : [];
  return [...direct, ...patch, ...workerCheckpoint];
}
```

- [ ] **Step 2: Update successful scenario expected events**

For `trivial-success.json`, `dirty-apply-block.json`, and
`overlapping-claims.json`, add `runway.checkpoint_created` after
`runway.verification_result`, then add `runway.apply_dry_run_result` after
`runway.checkpoint_created` in `expected.event_types`. Replace old logical
checkpoint refs with manifest refs like:

```json
"checkpoints": ["artifacts/checkpoints/task_trivial/candidate_task_trivial.json"]
```

Use the task and candidate ids from each scenario:

- `task_trivial` -> `candidate_task_trivial`
- `task_dirty_apply` -> `candidate_task_dirty_apply`
- `task_overlap_a` -> `candidate_task_overlap_a`

- [ ] **Step 3: Update missing-checkpoint and malformed-provider scenarios**

For `missing-checkpoint.json`, keep `checkpoints: []`, keep the blocker, and
update expected run status if runtime now blocks completion:

```json
"run_status": "failed",
"apply_status": "blocked"
```

For `malformed-provider.json`, keep no checkpoint and no checkpoint-created
event.

- [ ] **Step 4: Update Waygent skill stop rules**

In `skills/waygent/SKILL.md`, extend stop rules with:

```md
- If `resume` does not report `apply_verified_checkpoint`, do not run `apply`;
  inspect or explain the run first.
- If apply reports `checkpoint_manifest_missing`, `checkpoint_patch_missing`,
  or `checkpoint_digest_mismatch`, report the blocker and do not retry from
  chat.
```

- [ ] **Step 5: Update Waygent README operator notes**

In `skills/waygent/README.md`, add under stop rules:

```md
- Completed runs must have manifest-backed checkpoint artifacts before apply.
- `waygent resume --last` is the source of truth for whether apply is currently
  allowed.
- Missing or corrupted checkpoint artifacts require inspection or checkpoint
  regeneration; chat should not invent a patch or bypass the run state.
```

- [ ] **Step 6: Run scenario and skill gates**

Run:

```bash
bun run waygent:scenarios
skills/waygent/evals/run.sh
```

Expected:

```text
all scenario tests pass
skill contract checks pass
```

- [ ] **Step 7: Run full project verification**

Run:

```bash
bun run check
git diff --check
```

Expected:

```text
bun run check exits 0
git diff --check prints no output
```

- [ ] **Step 8: Review before final report**

Run:

```bash
git status --short --branch --untracked-files=all
git log --oneline -n 6
```

Expected:

```text
Only intentional changes remain, and task commits are visible at the top of history.
```

- [ ] **Step 9: Commit Task 6**

```bash
git add packages/testkit/src/waygentScenarioHarness.ts tests/waygent-scenarios skills/waygent/SKILL.md skills/waygent/README.md
git commit -m "test: update Waygent checkpoint apply scenarios"
```

## Final Review Checklist

- [ ] Read `code_review.md`.
- [ ] Confirm `completed` run state is impossible without checkpoint manifests.
- [ ] Confirm `resumeRun()` and `applyRun()` use the same checkpoint readiness contract.
- [ ] Confirm dirty checkout and digest mismatch are blocked without mutation.
- [ ] Confirm post-apply verification failure records evidence.
- [ ] Confirm no active `kws-cpe.*` or `kws-cme.*` runtime references were added.
- [ ] Confirm final commands passed:

```bash
bun test packages/orchestrator/tests packages/runway-control/tests
bun run waygent:scenarios
skills/waygent/evals/run.sh
bun run check
git diff --check
```
