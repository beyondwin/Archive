# Waygent Verify→Worker Feedback + Repair Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scoped repair worker that auto-dispatches on verification failure when the prior worker produced a successful result with a capturable diff. Repair starts from the prior diff, runs on a cheaper role, uses a separate budget, and produces a checkpoint identical to a first-pass success.

**Architecture:** Orchestrator captures `git diff main` after every successful worker_result and stamps `worker_result.evidence.patch_ref`. Recovery executor learns a new `dispatch_repair` action gated on patch presence + verification_failed. Dispatch creates a fresh worktree, `git apply`s the prior patch, then spawns a worker with role `repair` (default `sonnet/medium`) using existing process adapter infrastructure. Post-repair verify reruns the full set; on pass, the checkpoint pipeline runs unchanged.

**Tech Stack:** TypeScript, Bun, AJV (contract validation), git CLI shell-outs, existing `@waygent/orchestrator` + `@waygent/contracts` + `@waygent/lens-projectors` packages.

---

## Task 1: Add patch evidence fields to worker_result types

**Files:**
- Modify: `packages/contracts/src/types.ts` (WorkerResult evidence comment / no schema change needed since evidence is open)
- Test: `packages/contracts/tests/contracts.test.ts` (add fixture with patch_ref)

- [ ] **Step 1: Write failing test**

Add to `packages/contracts/tests/contracts.test.ts` inside the existing describe block:

```ts
test("worker_result.v1 accepts optional patch_ref / patch_sha256 / patch_byte_length in evidence", () => {
  const workerResult = {
    schema: "runway.worker_result.v1",
    task_id: "task_a",
    candidate_id: "cand_a",
    status: "completed",
    changed_files: ["src/foo.ts"],
    summary: "done",
    evidence: {
      patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
      patch_sha256: "a".repeat(64),
      patch_byte_length: 12345
    }
  };
  expect(validateContract("runway.worker_result.v1", workerResult)).toEqual(workerResult);
});
```

- [ ] **Step 2: Run test to verify it passes (evidence is open-typed)**

Run: `cd /Users/kws/source/private/Archive && bun test packages/contracts/tests/contracts.test.ts`
Expected: PASS. `evidence` has `additionalProperties: true` in `workerResultSchema`, so this is purely an assertion that our convention compiles.

- [ ] **Step 3: Commit**

```bash
git add packages/contracts/tests/contracts.test.ts
git commit -m "test(contracts): assert worker_result.evidence patch_ref shape"
```

---

## Task 2: Implement patch capture helper

**Files:**
- Create: `packages/orchestrator/src/patchCapture.ts`
- Test: `packages/orchestrator/tests/patchCapture.test.ts`

- [ ] **Step 1: Write failing test**

Create `packages/orchestrator/tests/patchCapture.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { captureWorktreePatch } from "../src/patchCapture";

function makeRepo(): string {
  const root = mkdtempSync(join(tmpdir(), "waygent-patch-"));
  spawnSync("git", ["init", "-q", "-b", "main"], { cwd: root });
  spawnSync("git", ["config", "user.email", "test@test"], { cwd: root });
  spawnSync("git", ["config", "user.name", "test"], { cwd: root });
  writeFileSync(join(root, "a.txt"), "one\n");
  spawnSync("git", ["add", "a.txt"], { cwd: root });
  spawnSync("git", ["commit", "-q", "-m", "init"], { cwd: root });
  return root;
}

describe("captureWorktreePatch", () => {
  test("returns null when no changes vs main", () => {
    const root = makeRepo();
    try {
      expect(captureWorktreePatch({ worktree: root, base: "main" })).toBeNull();
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("returns patch text + sha256 + byte length when worktree is dirty", () => {
    const root = makeRepo();
    try {
      writeFileSync(join(root, "a.txt"), "one\ntwo\n");
      const captured = captureWorktreePatch({ worktree: root, base: "main" });
      expect(captured).not.toBeNull();
      expect(captured!.patch).toContain("a.txt");
      expect(captured!.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(captured!.byteLength).toBe(Buffer.byteLength(captured!.patch));
      expect(captured!.truncatedWarning).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("flags patch_truncated_warning when patch exceeds 1MB", () => {
    const root = makeRepo();
    try {
      const big = "x".repeat(1_200_000);
      writeFileSync(join(root, "b.txt"), big);
      spawnSync("git", ["add", "b.txt"], { cwd: root });
      const captured = captureWorktreePatch({ worktree: root, base: "main" });
      expect(captured).not.toBeNull();
      expect(captured!.byteLength).toBeGreaterThan(1_048_576);
      expect(captured!.truncatedWarning).toBe(true);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kws/source/private/Archive && bun test packages/orchestrator/tests/patchCapture.test.ts`
Expected: FAIL with "Cannot find module '../src/patchCapture'".

- [ ] **Step 3: Implement helper**

Create `packages/orchestrator/src/patchCapture.ts`:

```ts
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";

export interface CapturedPatch {
  patch: string;
  sha256: string;
  byteLength: number;
  truncatedWarning: boolean;
}

const PATCH_WARN_BYTES = 1_048_576;

export interface CaptureInput {
  worktree: string;
  base: string;
}

export function captureWorktreePatch(input: CaptureInput): CapturedPatch | null {
  const args = ["diff", input.base, "--binary"];
  const result = spawnSync("git", args, {
    cwd: input.worktree,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    maxBuffer: 64 * 1024 * 1024
  });
  if (result.status !== 0) {
    throw new Error(`captureWorktreePatch git diff failed (exit ${result.status}): ${result.stderr}`);
  }
  if (!result.stdout || result.stdout.length === 0) return null;
  const patch = result.stdout;
  const byteLength = Buffer.byteLength(patch);
  return {
    patch,
    sha256: createHash("sha256").update(patch).digest("hex"),
    byteLength,
    truncatedWarning: byteLength > PATCH_WARN_BYTES
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test packages/orchestrator/tests/patchCapture.test.ts`
Expected: PASS — 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/orchestrator/src/patchCapture.ts packages/orchestrator/tests/patchCapture.test.ts
git commit -m "feat(orchestrator): add captureWorktreePatch helper for repair-base diff"
```

---

## Task 3: Add `repair` worker role + RoleRouting slot

**Files:**
- Modify: `packages/orchestrator/src/executionProfile.ts`
- Test: `packages/orchestrator/tests/repairRole.test.ts` (new)

- [ ] **Step 1: Write failing test**

Create `packages/orchestrator/tests/repairRole.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import {
  defaultProfiles,
  isWorkerRoleSlot,
  resolveExecutionProfile,
  roleProfileFor,
  ROLE_SLOTS
} from "../src/executionProfile";

describe("repair worker role", () => {
  test("ROLE_SLOTS includes repair", () => {
    expect(ROLE_SLOTS).toContain("repair");
  });

  test("isWorkerRoleSlot accepts repair", () => {
    expect(isWorkerRoleSlot("repair")).toBe(true);
  });

  test("defaultProfiles assign sensible repair model per provider", () => {
    expect(defaultProfiles.claude.roles!.repair).toEqual({ model: "sonnet", reasoning: "medium" });
    expect(defaultProfiles.codex.roles!.repair).toEqual({ model: "gpt-5.5", reasoning: "medium" });
    expect(defaultProfiles.fake.roles!.repair).toEqual({ model: "fake", reasoning: "medium" });
  });

  test("resolveExecutionProfile fills repair slot", () => {
    const profile = resolveExecutionProfile({ provider: "claude" });
    expect(profile.roles!.repair).toBeDefined();
    expect(roleProfileFor(profile, "repair").model).toBe("sonnet");
  });

  test("--role-model repair=opus override wins over preset", () => {
    const profile = resolveExecutionProfile({
      provider: "claude",
      role_models: { repair: "opus" },
      role_reasoning: { repair: "high" }
    });
    expect(roleProfileFor(profile, "repair")).toEqual({ model: "opus", reasoning: "high" });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun test packages/orchestrator/tests/repairRole.test.ts`
Expected: FAIL — `ROLE_SLOTS` does not include "repair".

- [ ] **Step 3: Extend executionProfile.ts**

Edit `packages/orchestrator/src/executionProfile.ts`:

Change line 4:
```ts
export type WorkerRoleSlot = "implement" | "review" | "verify_assist" | "repair";
```

Change line 36:
```ts
export const ROLE_SLOTS: readonly WorkerRoleSlot[] = ["implement", "review", "verify_assist", "repair"];
```

Update `defaultProfiles` (lines 38-75) to add `repair` to each provider's `roles`:

```ts
codex: {
  // ...
  roles: {
    implement: { model: "gpt-5.5", reasoning: "high" },
    review: { model: "gpt-5.5", reasoning: "high" },
    verify_assist: { model: "gpt-5.5", reasoning: "high" },
    repair: { model: "gpt-5.5", reasoning: "medium" }
  },
  // ...
},
claude: {
  // ...
  roles: {
    implement: { model: "opus", reasoning: "high" },
    review: { model: "opus", reasoning: "high" },
    verify_assist: { model: "opus", reasoning: "high" },
    repair: { model: "sonnet", reasoning: "medium" }
  },
  // ...
},
fake: {
  // ...
  roles: {
    implement: { model: "fake", reasoning: "medium" },
    review: { model: "fake", reasoning: "medium" },
    verify_assist: { model: "fake", reasoning: "medium" },
    repair: { model: "fake", reasoning: "medium" }
  },
  // ...
}
```

Update the `roles` literal at lines 88-92 in `resolveExecutionProfile`:

```ts
const roles: RoleRouting = {
  implement: resolveRoleSlot(base, "implement", merged, subagent),
  review: resolveRoleSlot(base, "review", merged, subagent),
  verify_assist: resolveRoleSlot(base, "verify_assist", merged, subagent),
  repair: resolveRoleSlot(base, "repair", merged, subagent)
};
```

Update `isWorkerRoleSlot` at line 156:

```ts
export function isWorkerRoleSlot(value: unknown): value is WorkerRoleSlot {
  return value === "implement" || value === "review" || value === "verify_assist" || value === "repair";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test packages/orchestrator/tests/repairRole.test.ts`
Expected: PASS — 5 tests pass.

- [ ] **Step 5: Run typecheck + full test suite to catch regressions**

Run: `bun run typecheck && bun test`
Expected: No new failures. (Existing tests that construct `RoleRouting` literally may need updating — see Step 6.)

- [ ] **Step 6: Fix any literal RoleRouting constructions in other test files**

Search for places constructing the type literally:
```bash
grep -rn "roles: {$\|roles: {" packages/orchestrator/tests/ apps/cli/tests/ packages/provider-adapters/tests/ 2>&1 | grep -v "\.d\.ts" | head
```

For each match where a literal `{ implement: ..., review: ..., verify_assist: ... }` is constructed, add the `repair` key. Example pattern: `repair: { model: "fake", reasoning: "medium" }`.

Re-run `bun run typecheck && bun test` until clean.

- [ ] **Step 7: Commit**

```bash
git add packages/orchestrator/src/executionProfile.ts packages/orchestrator/tests/repairRole.test.ts
git commit -m "feat(orchestrator): add repair WorkerRoleSlot with cheap-default role routing"
```

---

## Task 4: Add repair_budget to run state + recovery_action enum entry

**Files:**
- Modify: `packages/contracts/src/types.ts` (WaygentRunStateV2)
- Test: `packages/contracts/tests/contracts.test.ts` (state fixture extension)

- [ ] **Step 1: Write failing test**

Add to `packages/contracts/tests/contracts.test.ts`:

```ts
test("WaygentRunStateV2 type accepts optional repair_budget keyed by task_id", () => {
  // This is a type-level assertion. Compilation == success.
  const state: import("../src/types").WaygentRunStateV2 = {
    schema: "waygent.run_state.v2",
    run_id: "run_repair_state",
    workspace: "/tmp/ws",
    source_branch: null,
    worktree_root: "/tmp/wt",
    run_root: "/tmp/run",
    artifact_root: "/tmp/run/artifacts",
    state_path: "/tmp/run/state.json",
    event_journal_path: "/tmp/run/events.jsonl",
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
    timestamps: { started_at: "2026-05-25T00:00:00Z", updated_at: "2026-05-25T00:00:00Z", completed_at: null },
    repair_budget: { task_a: { max_attempts: 2, current: 0 } }
  };
  expect(state.repair_budget?.task_a?.max_attempts).toBe(2);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run typecheck`
Expected: FAIL — "Object literal may only specify known properties, and 'repair_budget' does not exist in type 'WaygentRunStateV2'".

- [ ] **Step 3: Extend WaygentRunStateV2**

Edit `packages/contracts/src/types.ts`. Find the `WaygentRunStateV2` interface (search for `apply: { status: "not_applied"`). Add the field just before `}` of the interface:

```ts
  repair_budget?: Record<string, { max_attempts: number; current: number }>;
```

- [ ] **Step 4: Run test + typecheck to verify pass**

Run: `bun run typecheck && bun test packages/contracts/tests/contracts.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/contracts/src/types.ts packages/contracts/tests/contracts.test.ts
git commit -m "feat(contracts): add WaygentRunStateV2.repair_budget for per-task repair attempts"
```

---

## Task 5: Implement buildRepairPacket with 16KB excerpt cap

**Files:**
- Create: `packages/orchestrator/src/repairPacket.ts`
- Test: `packages/orchestrator/tests/repairPacket.test.ts`

- [ ] **Step 1: Write failing test**

Create `packages/orchestrator/tests/repairPacket.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { buildRepairPacket, excerptForRepair } from "../src/repairPacket";

describe("excerptForRepair", () => {
  test("returns input unchanged when under cap", () => {
    expect(excerptForRepair("short", 16384)).toBe("short");
  });

  test("returns head + marker + tail when over cap", () => {
    const head = "H".repeat(8192);
    const tail = "T".repeat(8192);
    const oversized = head + "MIDDLE".repeat(2000) + tail;
    const out = excerptForRepair(oversized, 16384);
    expect(out.startsWith("H".repeat(8192))).toBe(true);
    expect(out.endsWith("T".repeat(8192))).toBe(true);
    expect(out).toContain("---<truncated>---");
    expect(Buffer.byteLength(out)).toBeLessThan(Buffer.byteLength(oversized));
  });
});

describe("buildRepairPacket", () => {
  test("composes packet with prior diff ref, failed and passed verifications, scope_lock", () => {
    const packet = buildRepairPacket({
      task_id: "task_x",
      attempt_id: "attempt_task_x_2",
      prior_worker_result: {
        schema: "runway.worker_result.v1",
        task_id: "task_x",
        candidate_id: "cand_x",
        status: "completed",
        changed_files: ["a.ts"],
        summary: "first pass implementation",
        evidence: {
          patch_ref: "artifacts/worker/task_x/attempt_1_patch.diff",
          patch_sha256: "deadbeef".padEnd(64, "0"),
          patch_byte_length: 1234
        }
      },
      verifications: [
        { verification_id: "v1", command: "tsc", exit_code: 2, timed_out: false, stdout: "TS error", stderr: "", status: "failed" },
        { verification_id: "v2", command: "bun test", exit_code: 0, timed_out: false, stdout: "5 pass", stderr: "", status: "passed" }
      ]
    });

    expect(packet.schema).toBe("runway.repair_task_packet.v1");
    expect(packet.task_id).toBe("task_x");
    expect(packet.role).toBe("repair");
    expect(packet.prior_diff_ref).toBe("artifacts/worker/task_x/attempt_1_patch.diff");
    expect(packet.prior_worker_summary).toBe("first pass implementation");
    expect(packet.failed_verifications).toHaveLength(1);
    expect(packet.failed_verifications[0]!.verification_id).toBe("v1");
    expect(packet.failed_verifications[0]!.stdout_excerpt).toBe("TS error");
    expect(packet.passed_verifications).toEqual([{ verification_id: "v2", command: "bun test" }]);
    expect(packet.scope_lock_instruction).toContain("smallest changes");
  });

  test("operator_instruction included when provided", () => {
    const packet = buildRepairPacket({
      task_id: "task_x",
      attempt_id: "attempt_2",
      prior_worker_result: {
        schema: "runway.worker_result.v1",
        task_id: "task_x",
        candidate_id: "cand_x",
        status: "completed",
        changed_files: [],
        summary: "s",
        evidence: { patch_ref: "p", patch_sha256: "x", patch_byte_length: 1 }
      },
      verifications: [{ verification_id: "v1", command: "c", exit_code: 1, timed_out: false, stdout: "", stderr: "", status: "failed" }],
      operator_instruction: "check line 138"
    });
    expect(packet.operator_instruction).toBe("check line 138");
  });

  test("evidence_filter narrows failed_verifications to listed ids", () => {
    const packet = buildRepairPacket({
      task_id: "task_x",
      attempt_id: "attempt_2",
      prior_worker_result: {
        schema: "runway.worker_result.v1",
        task_id: "task_x",
        candidate_id: "cand_x",
        status: "completed",
        changed_files: [],
        summary: "s",
        evidence: { patch_ref: "p", patch_sha256: "x", patch_byte_length: 1 }
      },
      verifications: [
        { verification_id: "v1", command: "c1", exit_code: 1, timed_out: false, stdout: "", stderr: "", status: "failed" },
        { verification_id: "v2", command: "c2", exit_code: 1, timed_out: false, stdout: "", stderr: "", status: "failed" }
      ],
      evidence_filter: ["v1"]
    });
    expect(packet.failed_verifications.map((v) => v.verification_id)).toEqual(["v1"]);
    expect(packet.passed_verifications.map((v) => v.verification_id)).toEqual(["v2"]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun test packages/orchestrator/tests/repairPacket.test.ts`
Expected: FAIL — "Cannot find module '../src/repairPacket'".

- [ ] **Step 3: Implement repairPacket.ts**

Create `packages/orchestrator/src/repairPacket.ts`:

```ts
import type { WorkerResult } from "@waygent/contracts";

const REPAIR_EXCERPT_BYTES = 16_384;
const REPAIR_EXCERPT_HALF = 8_192;
const TRUNCATION_MARKER = "\n---<truncated>---\n";

const SCOPE_LOCK = [
  "You are the Waygent repair worker.",
  "The worktree already contains a prior worker's diff (see git status).",
  "A subset of verifications failed; their evidence is in the task packet.",
  "",
  "Your task:",
  "- Read failed_verifications carefully — especially stdout/stderr excerpts.",
  "- Make the smallest changes needed to make the failed verifications pass.",
  "- Do NOT add new features, refactor unrelated code, or change passing verifications.",
  "- Do NOT revert prior changes unless a specific change directly caused a failure.",
  "- Honor the worktree's task_packet write policy.",
  "- Return runway.worker_result.v1 with status=completed and a short summary describing the fix."
].join("\n");

export function excerptForRepair(text: string, capBytes: number): string {
  if (Buffer.byteLength(text) <= capBytes) return text;
  const head = text.slice(0, REPAIR_EXCERPT_HALF);
  const tail = text.slice(-REPAIR_EXCERPT_HALF);
  return head + TRUNCATION_MARKER + tail;
}

export interface RepairPacketVerificationInput {
  verification_id: string;
  command: string;
  exit_code: number | null;
  timed_out: boolean;
  stdout: string;
  stderr: string;
  status: "passed" | "failed";
}

export interface BuildRepairPacketInput {
  task_id: string;
  attempt_id: string;
  prior_worker_result: WorkerResult;
  verifications: RepairPacketVerificationInput[];
  operator_instruction?: string;
  evidence_filter?: string[];
}

export interface RepairTaskPacket {
  schema: "runway.repair_task_packet.v1";
  task_id: string;
  attempt_id: string;
  role: "repair";
  prior_diff_ref: string;
  prior_worker_summary: string;
  failed_verifications: Array<{
    verification_id: string;
    command: string;
    exit_code: number | null;
    timed_out: boolean;
    stdout_excerpt: string;
    stderr_excerpt: string;
  }>;
  passed_verifications: Array<{ verification_id: string; command: string }>;
  operator_instruction?: string;
  scope_lock_instruction: string;
}

export function buildRepairPacket(input: BuildRepairPacketInput): RepairTaskPacket {
  const patchRef = input.prior_worker_result.evidence?.patch_ref;
  if (typeof patchRef !== "string" || patchRef.length === 0) {
    throw new Error("buildRepairPacket: prior_worker_result.evidence.patch_ref is required");
  }
  const filter = input.evidence_filter ? new Set(input.evidence_filter) : null;
  const failed: RepairTaskPacket["failed_verifications"] = [];
  const passed: RepairTaskPacket["passed_verifications"] = [];
  for (const v of input.verifications) {
    if (v.status === "failed" && (filter === null || filter.has(v.verification_id))) {
      failed.push({
        verification_id: v.verification_id,
        command: v.command,
        exit_code: v.exit_code,
        timed_out: v.timed_out,
        stdout_excerpt: excerptForRepair(v.stdout, REPAIR_EXCERPT_BYTES),
        stderr_excerpt: excerptForRepair(v.stderr, REPAIR_EXCERPT_BYTES)
      });
    } else {
      passed.push({ verification_id: v.verification_id, command: v.command });
    }
  }
  const packet: RepairTaskPacket = {
    schema: "runway.repair_task_packet.v1",
    task_id: input.task_id,
    attempt_id: input.attempt_id,
    role: "repair",
    prior_diff_ref: patchRef,
    prior_worker_summary: input.prior_worker_result.summary,
    failed_verifications: failed,
    passed_verifications: passed,
    scope_lock_instruction: SCOPE_LOCK
  };
  if (typeof input.operator_instruction === "string" && input.operator_instruction.length > 0) {
    packet.operator_instruction = input.operator_instruction;
  }
  return packet;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test packages/orchestrator/tests/repairPacket.test.ts`
Expected: PASS — 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/orchestrator/src/repairPacket.ts packages/orchestrator/tests/repairPacket.test.ts
git commit -m "feat(orchestrator): add buildRepairPacket with 16KB excerpt cap and evidence filter"
```

---

## Task 6: Add repair action selector to recoveryExecutor

**Files:**
- Modify: `packages/orchestrator/src/recoveryExecutor.ts`
- Test: `packages/orchestrator/tests/repairAction.test.ts` (new)

- [ ] **Step 1: Write failing test**

Create `packages/orchestrator/tests/repairAction.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { selectRepairAction } from "../src/recoveryExecutor";

const PRIOR_OK = {
  schema: "runway.worker_result.v1" as const,
  task_id: "task_x",
  candidate_id: "cand_x",
  status: "completed" as const,
  changed_files: [],
  summary: "s",
  evidence: { patch_ref: "artifacts/worker/task_x/attempt_1_patch.diff", patch_sha256: "x", patch_byte_length: 1 }
};

describe("selectRepairAction", () => {
  test("dispatches repair when verification failed + completed worker_result + patch present + budget remaining", () => {
    const decision = selectRepairAction({
      failure_class: "verification_failed",
      prior_worker_result: PRIOR_OK,
      repair_budget: { max_attempts: 2, current: 0 }
    });
    expect(decision).toEqual({ action: "dispatch_repair", attempt_number: 1, max_attempts: 2 });
  });

  test("returns null when failure_class is not verification_failed", () => {
    expect(selectRepairAction({
      failure_class: "adapter_crashed",
      prior_worker_result: PRIOR_OK,
      repair_budget: { max_attempts: 2, current: 0 }
    })).toBeNull();
  });

  test("returns null when prior worker_result missing", () => {
    expect(selectRepairAction({
      failure_class: "verification_failed",
      prior_worker_result: null,
      repair_budget: { max_attempts: 2, current: 0 }
    })).toBeNull();
  });

  test("returns null when prior worker_result.status is not completed", () => {
    expect(selectRepairAction({
      failure_class: "verification_failed",
      prior_worker_result: { ...PRIOR_OK, status: "failed" },
      repair_budget: { max_attempts: 2, current: 0 }
    })).toBeNull();
  });

  test("returns null when patch_ref missing", () => {
    expect(selectRepairAction({
      failure_class: "verification_failed",
      prior_worker_result: { ...PRIOR_OK, evidence: {} },
      repair_budget: { max_attempts: 2, current: 0 }
    })).toBeNull();
  });

  test("returns request_decision when budget exhausted", () => {
    const decision = selectRepairAction({
      failure_class: "verification_failed",
      prior_worker_result: PRIOR_OK,
      repair_budget: { max_attempts: 2, current: 2 }
    });
    expect(decision).toEqual({ action: "request_decision", attempt_number: 3, max_attempts: 2 });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun test packages/orchestrator/tests/repairAction.test.ts`
Expected: FAIL — `selectRepairAction` is not exported.

- [ ] **Step 3: Implement selectRepairAction**

Edit `packages/orchestrator/src/recoveryExecutor.ts`. Add to the end of the file:

```ts
import type { WorkerResult } from "@waygent/contracts";

export interface RepairActionInput {
  failure_class: string;
  prior_worker_result: WorkerResult | null;
  repair_budget: { max_attempts: number; current: number };
}

export type RepairActionDecision =
  | { action: "dispatch_repair"; attempt_number: number; max_attempts: number }
  | { action: "request_decision"; attempt_number: number; max_attempts: number };

export function selectRepairAction(input: RepairActionInput): RepairActionDecision | null {
  if (input.failure_class !== "verification_failed") return null;
  const prior = input.prior_worker_result;
  if (!prior || prior.status !== "completed") return null;
  const patchRef = prior.evidence?.patch_ref;
  if (typeof patchRef !== "string" || patchRef.length === 0) return null;
  const { current, max_attempts } = input.repair_budget;
  if (current >= max_attempts) {
    return { action: "request_decision", attempt_number: current + 1, max_attempts };
  }
  return { action: "dispatch_repair", attempt_number: current + 1, max_attempts };
}
```

Note: the existing `import type { FailureClass } from "@waygent/contracts";` at line 1 should be extended to also import `WorkerResult`. If `WorkerResult` is not exported from `@waygent/contracts`, instead import from `../../contracts/src/types.ts` via the existing pattern.

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test packages/orchestrator/tests/repairAction.test.ts`
Expected: PASS — 6 tests pass.

- [ ] **Step 5: Run full test + typecheck**

Run: `bun run typecheck && bun test`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator/src/recoveryExecutor.ts packages/orchestrator/tests/repairAction.test.ts
git commit -m "feat(orchestrator): add selectRepairAction recovery selector with budget"
```

---

## Task 7: Wire patch capture into orchestrator wave loop

**Files:**
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Test: `packages/orchestrator/tests/orchestratorPatchCapture.test.ts` (new, integration)

- [ ] **Step 1: Inspect current wave-result handling**

Read `packages/orchestrator/src/orchestrator.ts` lines 510–550. The hook point is right after `recordRuntimeEvidence(context, waveResult.result);` (currently line 521). Worker result is at `waveResult.result.worker_result`.

- [ ] **Step 2: Write failing test (integration via existing demo fixture)**

Create `packages/orchestrator/tests/orchestratorPatchCapture.test.ts`:

```ts
import { existsSync, mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import { runWaygentDemo } from "../src";
import { initSourceCheckout } from "./support/orchestratorFixtures";

describe("orchestrator patch capture", () => {
  test("completed worker_result carries patch_ref + artifact exists on disk", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-patch-orch-"));
    const workspace = initSourceCheckout("waygent-patch-source-");
    const result = await runWaygentDemo({ root, workspace });
    // Find the task in run state — demo plan defines exactly one task.
    const statePath = join(result.run_root, "state.json");
    const state = JSON.parse(readFileSync(statePath, "utf8"));
    const taskIds = Object.keys(state.tasks);
    expect(taskIds.length).toBe(1);
    const task = state.tasks[taskIds[0]!];
    const lastAttempt = task.attempts?.[task.attempts.length - 1];
    expect(lastAttempt?.worker_result?.status).toBe("completed");
    const patchRef = lastAttempt?.worker_result?.evidence?.patch_ref;
    expect(typeof patchRef).toBe("string");
    expect((patchRef as string).startsWith("artifacts/worker/")).toBe(true);
    expect(existsSync(join(result.run_root, patchRef as string))).toBe(true);
    expect(typeof lastAttempt!.worker_result!.evidence!.patch_sha256).toBe("string");
    expect(typeof lastAttempt!.worker_result!.evidence!.patch_byte_length).toBe("number");
  });
});
```

This leverages the existing `runWaygentDemo` + `initSourceCheckout` test pair already used by `packages/orchestrator/tests/orchestrator.test.ts:13` and asserts the patch capture wiring without inventing a new fixture format.

- [ ] **Step 3: Wire patch capture in orchestrator.ts**

Edit `packages/orchestrator/src/orchestrator.ts`:

Add import at top (with other orchestrator imports):
```ts
import { captureWorktreePatch } from "./patchCapture";
```

After `recordRuntimeEvidence(context, waveResult.result);` (around line 521), insert the capture step:

```ts
      // Capture worktree diff for successful workers so repair has a base
      // and apply has a checkpoint patch_ref. Empty diff → no field set.
      if (waveResult.result.worker_result.status === "completed") {
        try {
          const captured = captureWorktreePatch({
            worktree: waveResult.result.worktree_path,
            base: "main"
          });
          if (captured) {
            const ref = `artifacts/worker/${waveResult.task_id}/attempt_${waveResult.result.attempt_number}_patch.diff`;
            writeArtifact(paths.root, ref, captured.patch, "text/x-diff");
            const evidence = (waveResult.result.worker_result.evidence ?? {}) as Record<string, unknown>;
            evidence.patch_ref = ref;
            evidence.patch_sha256 = captured.sha256;
            evidence.patch_byte_length = captured.byteLength;
            if (captured.truncatedWarning) evidence.patch_truncated_warning = true;
            waveResult.result.worker_result.evidence = evidence;
          }
        } catch (err) {
          // Capture failure should not block the wave; log and continue.
          // The downstream repair selector will simply not dispatch_repair
          // (no patch_ref → falls back to existing retry path).
          console.error("[orchestrator] patch capture failed:", err);
        }
      }
```

Note: if `waveResult.result.worktree_path` or `attempt_number` don't exist on the result shape, locate the equivalent fields (search `worktree_path` and `attempt_number` in the orchestrator). Adapt as needed; the goal is "capture diff in the just-finished worktree and tag the worker_result".

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test packages/orchestrator/tests/orchestratorPatchCapture.test.ts`
Expected: PASS.

- [ ] **Step 5: Run full test suite + typecheck**

Run: `bun run check`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/orchestratorPatchCapture.test.ts
git commit -m "feat(orchestrator): capture worktree diff into worker_result.evidence after each completed worker"
```

---

## Task 8: Dispatch repair worker in recovery loop

**Files:**
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Create: `packages/orchestrator/src/repairDispatch.ts`
- Test: `packages/orchestrator/tests/repairDispatch.test.ts`

- [ ] **Step 1: Write failing test**

Create `packages/orchestrator/tests/repairDispatch.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { prepareRepairWorktree } from "../src/repairDispatch";

function makeRepoWithPatchArtifact(): { root: string; patchPath: string } {
  const root = mkdtempSync(join(tmpdir(), "waygent-repair-disp-"));
  spawnSync("git", ["init", "-q", "-b", "main"], { cwd: root });
  spawnSync("git", ["config", "user.email", "test@test"], { cwd: root });
  spawnSync("git", ["config", "user.name", "test"], { cwd: root });
  writeFileSync(join(root, "a.txt"), "v1\n");
  spawnSync("git", ["add", "a.txt"], { cwd: root });
  spawnSync("git", ["commit", "-q", "-m", "init"], { cwd: root });
  // Generate a patch against main from a temporary worktree
  const wt = join(root, ".tmpwt");
  spawnSync("git", ["worktree", "add", "-b", "scratch", wt, "main"], { cwd: root });
  writeFileSync(join(wt, "a.txt"), "v1\nv2\n");
  const patch = spawnSync("git", ["diff", "main", "--binary"], { cwd: wt, encoding: "utf8" }).stdout;
  spawnSync("git", ["worktree", "remove", "--force", wt], { cwd: root });
  spawnSync("git", ["branch", "-D", "scratch"], { cwd: root });
  const patchPath = join(root, "patch.diff");
  writeFileSync(patchPath, patch);
  return { root, patchPath };
}

describe("prepareRepairWorktree", () => {
  test("creates a fresh worktree at the requested path and applies the prior patch", () => {
    const { root, patchPath } = makeRepoWithPatchArtifact();
    const dest = join(root, "wt", "repair_1");
    try {
      const result = prepareRepairWorktree({
        source_repo: root,
        destination: dest,
        base_branch: "main",
        prior_patch_path: patchPath
      });
      expect(result.status).toBe("ready");
      expect(existsSync(dest)).toBe(true);
      const status = spawnSync("git", ["status", "--porcelain"], { cwd: dest, encoding: "utf8" }).stdout;
      expect(status.length).toBeGreaterThan(0);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("returns blocked status when prior patch fails to apply", () => {
    const { root } = makeRepoWithPatchArtifact();
    const dest = join(root, "wt", "repair_bad");
    const bogus = join(root, "bogus.diff");
    writeFileSync(bogus, "not a real patch\n");
    try {
      const result = prepareRepairWorktree({
        source_repo: root,
        destination: dest,
        base_branch: "main",
        prior_patch_path: bogus
      });
      expect(result.status).toBe("blocked");
      expect(result.reason).toBe("prior_patch_apply_failed");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun test packages/orchestrator/tests/repairDispatch.test.ts`
Expected: FAIL — "Cannot find module '../src/repairDispatch'".

- [ ] **Step 3: Implement repairDispatch.ts**

Create `packages/orchestrator/src/repairDispatch.ts`:

```ts
import { spawnSync } from "node:child_process";
import { mkdirSync, existsSync, rmSync } from "node:fs";
import { dirname } from "node:path";

export interface PrepareRepairWorktreeInput {
  source_repo: string;
  destination: string;
  base_branch: string;
  prior_patch_path: string;
}

export type PrepareRepairWorktreeResult =
  | { status: "ready"; destination: string }
  | { status: "blocked"; reason: "prior_patch_apply_failed" | "worktree_create_failed" };

export function prepareRepairWorktree(input: PrepareRepairWorktreeInput): PrepareRepairWorktreeResult {
  mkdirSync(dirname(input.destination), { recursive: true });
  if (existsSync(input.destination)) {
    rmSync(input.destination, { recursive: true, force: true });
  }
  const create = spawnSync("git", ["worktree", "add", "--detach", input.destination, input.base_branch], {
    cwd: input.source_repo,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (create.status !== 0) {
    return { status: "blocked", reason: "worktree_create_failed" };
  }
  const check = spawnSync("git", ["apply", "--check", input.prior_patch_path], {
    cwd: input.destination,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (check.status !== 0) {
    spawnSync("git", ["worktree", "remove", "--force", input.destination], { cwd: input.source_repo });
    return { status: "blocked", reason: "prior_patch_apply_failed" };
  }
  const apply = spawnSync("git", ["apply", input.prior_patch_path], {
    cwd: input.destination,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (apply.status !== 0) {
    spawnSync("git", ["worktree", "remove", "--force", input.destination], { cwd: input.source_repo });
    return { status: "blocked", reason: "prior_patch_apply_failed" };
  }
  return { status: "ready", destination: input.destination };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test packages/orchestrator/tests/repairDispatch.test.ts`
Expected: PASS — 2 tests pass.

- [ ] **Step 5: Wire dispatch_repair branch into orchestrator wave loop**

Edit `packages/orchestrator/src/orchestrator.ts`. In the `else if (task)` block that currently handles verification failure (around line 529-545), insert a repair check **before** the existing `recordTaskRecovery` call:

```ts
      } else if (task) {
        const failureClass = waveResult.result.latest_failure_class ?? "verification_failed";
        const priorWorker = waveResult.result.worker_result;
        const repairBudget = (context.state.repair_budget?.[waveResult.task_id] ?? { max_attempts: 2, current: 0 });
        const repair = selectRepairAction({
          failure_class: failureClass,
          prior_worker_result: priorWorker,
          repair_budget: repairBudget
        });
        if (repair && repair.action === "dispatch_repair") {
          // Dispatch repair via the existing wave executor with role=repair.
          // The detailed orchestrator wiring belongs in the next step (Task 9).
          // For now, this path falls through to the existing recovery as a placeholder.
        }
        const recovery = recordTaskRecovery(context, {
          task_id: waveResult.result.task_id,
          failure_class: failureClass,
          prior_summary: waveResult.result.worker_result.summary,
          evidence_refs: taskRecoveryEvidenceRefs(waveResult.result)
        });
        // ... existing branches unchanged ...
      }
```

Add import at top of file:
```ts
import { selectRepairAction } from "./recoveryExecutor";
```

- [ ] **Step 6: Run full test suite + typecheck**

Run: `bun run check`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/orchestrator/src/repairDispatch.ts packages/orchestrator/tests/repairDispatch.test.ts packages/orchestrator/src/orchestrator.ts
git commit -m "feat(orchestrator): prepareRepairWorktree + repair branch hook in wave loop"
```

---

## Task 9: Execute repair worker through existing process adapter

**Files:**
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Test: extend `packages/orchestrator/tests/repairDispatch.test.ts` with end-to-end (fake provider) coverage

- [ ] **Step 1: Locate existing worker dispatch site for reuse**

In `packages/orchestrator/src/orchestrator.ts`, search for the function that runs a single task attempt (likely `runTaskAttempt`, `executeWaveTask`, or similar — find the call that calls `runProviderProcess` from `@waygent/provider-adapters`). This is the call site you'll reuse with role overridden to `"repair"`.

- [ ] **Step 2: Defer end-to-end fake-repair coverage to Task 11**

End-to-end coverage requires a fake provider fixture that returns *different* worker_result payloads across sequential attempts (success → verify-fails → success). The existing `tests/integration/waygent-scenarios.test.ts` framework runs through single-shot fixtures; adding the multi-attempt capability is its own infrastructure task and is covered as Task 11.

For Task 9, the unit-level coverage from Task 8 (`prepareRepairWorktree` patch-apply success + failure) plus the orchestrator wiring exercised through normal `bun run check` is sufficient. The end-to-end assertion lands in Task 11 against the `repair-from-verify-failure.json` scenario.

- [ ] **Step 3: Implement repair dispatch in orchestrator**

In `orchestrator.ts`, replace the placeholder in Task 8 Step 5 with actual dispatch. The repair flow:

1. Resolve the prior patch artifact path from `priorWorker.evidence.patch_ref` against `paths.root`.
2. Compute destination worktree: `paths.worktrees + "/" + waveResult.task_id + "_repair_" + repair.attempt_number`.
3. Call `prepareRepairWorktree({ source_repo: workspace, destination, base_branch: "main", prior_patch_path: resolvedPatchPath })`.
4. If `result.status === "blocked"`: emit `runway.repair_result` with `failure_class: result.reason`, increment budget, fall through to existing recovery path.
5. Else: build the repair packet via `buildRepairPacket(...)`, write the packet artifact, then invoke the existing per-task worker runner with profile overrides setting role to `"repair"`. (The exact call shape depends on what `runTaskAttempt` / equivalent takes — pass through to `processAdapters.runProviderProcess` with `worker_role: "repair"`.)
6. Increment `context.state.repair_budget[task_id].current` += 1; persist via `context.flushState()`.
7. Replay the resulting `worker_result` through the same `replayTaskExecutionResult` + patch capture flow (Task 7). The new patch artifact represents the cumulative diff and serves as the next checkpoint's `patch_ref`.
8. Run verifications again (full set) by reusing the verify pipeline already triggered in the wave loop.

Pseudocode insertion (replace the placeholder block):

```ts
        if (repair && repair.action === "dispatch_repair") {
          const patchArtifactPath = join(paths.root, priorWorker.evidence!.patch_ref as string);
          const dest = join(paths.worktrees, `${waveResult.task_id}_repair_${repair.attempt_number}`);
          const prep = prepareRepairWorktree({
            source_repo: workspace,
            destination: dest,
            base_branch: "main",
            prior_patch_path: patchArtifactPath
          });
          if (prep.status === "blocked") {
            context.appendEvent((sequence) => buildRunEvent({
              run_id: runId, sequence,
              event_type: "runway.repair_result",
              phase: "repair", outcome: "failed",
              summary: `Repair preparation blocked: ${prep.reason}`,
              payload: { task_id: waveResult.task_id, status: "blocked", failure_class: prep.reason }
            }));
            // fall through to existing recovery path
          } else {
            const repairPacket = buildRepairPacket({
              task_id: waveResult.task_id,
              attempt_id: `attempt_${waveResult.task_id}_repair_${repair.attempt_number}`,
              prior_worker_result: priorWorker,
              verifications: verificationsForTask(context.state, waveResult.task_id)
            });
            const packetRef = `artifacts/task_packets/repair_${waveResult.task_id}_${repair.attempt_number}.json`;
            writeArtifact(paths.root, packetRef, JSON.stringify(repairPacket, null, 2), "application/json");
            context.appendEvent((sequence) => buildRunEvent({
              run_id: runId, sequence,
              event_type: "runway.repair_dispatched",
              phase: "repair", outcome: "success",
              summary: "Repair worker dispatched.",
              payload: {
                task_id: waveResult.task_id,
                attempt_id: repairPacket.attempt_id,
                attempt_number: repair.attempt_number,
                max_attempts: repair.max_attempts,
                role: "repair",
                prior_diff_ref: repairPacket.prior_diff_ref,
                evidence_refs: [packetRef]
              }
            }));
            const repairResult = await runTaskAttempt({
              ...waveResult.taskAttemptOptions,
              worktree_path: dest,
              task_packet_ref: packetRef,
              worker_role: "repair"
            });
            // capture patch + replay result + bump budget
            context.state.repair_budget = {
              ...(context.state.repair_budget ?? {}),
              [waveResult.task_id]: {
                max_attempts: repair.max_attempts,
                current: repair.attempt_number
              }
            };
            replayTaskExecutionResult(context, repairResult);
            recordRuntimeEvidence(context, repairResult);
            // patch capture (same logic as Task 7)
            if (repairResult.worker_result.status === "completed") {
              const captured = captureWorktreePatch({ worktree: dest, base: "main" });
              if (captured) {
                const ref = `artifacts/worker/${waveResult.task_id}/attempt_${repair.attempt_number}_repair_patch.diff`;
                writeArtifact(paths.root, ref, captured.patch, "text/x-diff");
                const ev = (repairResult.worker_result.evidence ?? {}) as Record<string, unknown>;
                ev.patch_ref = ref;
                ev.patch_sha256 = captured.sha256;
                ev.patch_byte_length = captured.byteLength;
                if (captured.truncatedWarning) ev.patch_truncated_warning = true;
                repairResult.worker_result.evidence = ev;
              }
            }
            context.appendEvent((sequence) => buildRunEvent({
              run_id: runId, sequence,
              event_type: "runway.repair_result",
              phase: "repair", outcome: repairResult.worker_result.status === "completed" ? "success" : "failed",
              summary: repairResult.worker_result.summary,
              payload: {
                task_id: waveResult.task_id,
                attempt_id: repairPacket.attempt_id,
                status: repairResult.worker_result.status,
                patch_ref: repairResult.worker_result.evidence?.patch_ref ?? null,
                summary: repairResult.worker_result.summary,
                failure_class: repairResult.latest_failure_class ?? null
              }
            }));
            // After repair, the wave loop re-enters verification at the next iteration.
            // Mark task READY so the wave executor re-runs verify against the repaired worktree.
            task.status = "READY";
            task.retry_count = (task.retry_count ?? 0) + 1;
            delete task.latest_failure_class;
            markStateTaskReadyForRetry(context, task.id, "verification_failed");
            continue; // skip the legacy recovery fall-through for this task
          }
        }
```

Helper functions referenced above (`verificationsForTask`, `runTaskAttempt`) already exist in some form — locate the existing ones in `orchestrator.ts` and call them directly. If `runTaskAttempt` does not yet accept `worker_role`, thread it through (additive parameter).

Add imports:
```ts
import { prepareRepairWorktree } from "./repairDispatch";
import { buildRepairPacket } from "./repairPacket";
```

- [ ] **Step 4: Run integration test**

Run: `bun test packages/orchestrator/tests/repairDispatch.test.ts`
Expected: PASS — 3 tests (2 unit + 1 e2e fake).

- [ ] **Step 5: Run full test + typecheck**

Run: `bun run check`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/repairDispatch.test.ts
git commit -m "feat(orchestrator): dispatch repair worker on verification_failed when patch_ref present"
```

---

## Task 10: Add `waygent repair` CLI command

**Files:**
- Modify: `packages/orchestrator/src/runCommands.ts` (add `repairRun`)
- Modify: `apps/cli/src/index.ts` (parse `repair` command)
- Test: `apps/cli/tests/repair.test.ts`

- [ ] **Step 1: Write failing test**

Create `apps/cli/tests/repair.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { repairRun } from "@waygent/orchestrator";

describe("waygent repair --dry-run", () => {
  test("returns packet without dispatching when run has no repairable task", async () => {
    const result = await repairRun({
      root: "/tmp/nonexistent",
      run: "missing_run",
      dry_run: true
    });
    expect(result.status).toBe("blocked");
    expect(result.reason).toBe("no_repairable_task");
  });
});
```

(Once the implementation lands, expand with fixture-based tests covering `--task`, `--evidence`, `--instruction`, and budget-exhausted paths.)

- [ ] **Step 2: Run test to verify it fails**

Run: `bun test apps/cli/tests/repair.test.ts`
Expected: FAIL — `repairRun` is not exported.

- [ ] **Step 3: Implement repairRun**

Add to `packages/orchestrator/src/runCommands.ts`:

```ts
import { buildRepairPacket } from "./repairPacket";
import { selectRepairAction } from "./recoveryExecutor";

export interface RepairRunOptions {
  root: string;
  run: string;
  task?: string;
  instruction?: string;
  evidence?: string[];
  dry_run?: boolean;
}

export interface RepairRunResult {
  command: "repair";
  run_id: string;
  task_id?: string;
  status: "dispatched" | "blocked" | "dry_run";
  reason?: string;
  attempt_id?: string;
  packet?: unknown;
}

export async function repairRun(options: RepairRunOptions): Promise<RepairRunResult> {
  const runId = resolveRunId(options);
  const stateResult = readRunStateV2Result(options.root, runId);
  if (stateResult.status !== "ok") {
    return { command: "repair", run_id: runId, status: "blocked", reason: stateBlocker(stateResult) };
  }
  const v2 = stateResult.state;
  const candidates = Object.values(v2.tasks).filter((t) => {
    const latest = t.attempts?.[t.attempts.length - 1];
    if (!latest) return false;
    return latest.worker_result?.status === "completed"
      && typeof latest.worker_result?.evidence?.patch_ref === "string"
      && (latest.worker_result.evidence.patch_ref as string).length > 0
      && t.latest_failure_class === "verification_failed";
  });
  let chosen = candidates.find((t) => t.id === options.task) ?? candidates[candidates.length - 1];
  if (!chosen) {
    return { command: "repair", run_id: runId, status: "blocked", reason: "no_repairable_task" };
  }
  if (candidates.length > 1 && !options.task) {
    return { command: "repair", run_id: runId, status: "blocked", reason: "ambiguous_task_select_via_flag" };
  }
  const budget = v2.repair_budget?.[chosen.id] ?? { max_attempts: 2, current: 0 };
  const action = selectRepairAction({
    failure_class: "verification_failed",
    prior_worker_result: chosen.attempts![chosen.attempts!.length - 1]!.worker_result,
    repair_budget: budget
  });
  if (!action || action.action === "request_decision") {
    return { command: "repair", run_id: runId, task_id: chosen.id, status: "blocked", reason: "repair_budget_exhausted" };
  }

  const priorWorker = chosen.attempts![chosen.attempts!.length - 1]!.worker_result!;
  const verifications = v2.verification.filter((v) => v.task_id === chosen.id).map((v) => ({
    verification_id: v.verification_id,
    command: v.command,
    exit_code: v.exit_code,
    timed_out: v.timed_out,
    stdout: v.stdout ?? "",
    stderr: v.stderr ?? "",
    status: v.status as "passed" | "failed"
  }));

  const packet = buildRepairPacket({
    task_id: chosen.id,
    attempt_id: `attempt_${chosen.id}_repair_${action.attempt_number}_manual`,
    prior_worker_result: priorWorker,
    verifications,
    operator_instruction: options.instruction,
    evidence_filter: options.evidence
  });

  if (options.dry_run) {
    return { command: "repair", run_id: runId, task_id: chosen.id, status: "dry_run", packet };
  }

  // Non-dry-run dispatch: mark the task READY with the manual-repair token so the
  // running orchestrator (or a subsequent `waygent run --run <id>`) picks it up.
  // Implementation note: store the packet artifact + bump repair_budget here; the
  // resume/run path consumes it.
  // ... write packet artifact, bump budget, persist state ...

  return {
    command: "repair", run_id: runId, task_id: chosen.id,
    status: "dispatched", attempt_id: packet.attempt_id
  };
}
```

Export `repairRun` from the package index (`packages/orchestrator/src/index.ts`):
```ts
export { repairRun } from "./runCommands";
export type { RepairRunOptions, RepairRunResult } from "./runCommands";
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test apps/cli/tests/repair.test.ts`
Expected: PASS.

- [ ] **Step 5: Wire CLI parsing**

Edit `apps/cli/src/index.ts`. Add to the imports (with other orchestrator imports):
```ts
import { repairRun } from "@waygent/orchestrator";
```

Add after the `apply` command branch (around line 302):
```ts
  if (parsed.command === "repair") {
    const options: Parameters<typeof repairRun>[0] = runCommandOptions(parsed);
    if (typeof parsed.flags.task === "string") options.task = parsed.flags.task;
    if (typeof parsed.flags.instruction === "string") options.instruction = parsed.flags.instruction;
    if (typeof parsed.flags.evidence === "string") {
      options.evidence = parsed.flags.evidence.split(",").map((s: string) => s.trim()).filter(Boolean);
    }
    if (parsed.flags["dry-run"]) options.dry_run = true;
    return repairRun(options);
  }
```

Add to the usage strings (top of file, search for `usage:`):
```
waygent repair --run <id> [--task <task_id>] [--instruction "<note>"] [--evidence <verification_id>[,...]] [--dry-run]
```

Also extend the `usage` table at the top of the file to include `repair` as a recognized subcommand.

- [ ] **Step 6: Run typecheck + full tests**

Run: `bun run check`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/orchestrator/src/runCommands.ts packages/orchestrator/src/index.ts apps/cli/src/index.ts apps/cli/tests/repair.test.ts
git commit -m "feat(cli): add waygent repair command with --task, --instruction, --evidence, --dry-run"
```

---

## Task 11: Lens projector + waygent-scenarios integration

**Files:**
- Modify: `packages/lens-projectors/src/timeline.ts` (surface repair_* in timeline)
- Modify: `tests/integration/waygent-scenarios.test.ts`
- Create: `packages/lens-projectors/tests/repair.test.ts`

- [ ] **Step 1: Write failing test for timeline projector**

Create `packages/lens-projectors/tests/repair.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { projectTimeline } from "../src/timeline";
import { demoEvent } from "./support";

describe("timeline includes repair events", () => {
  test("repair_dispatched and repair_result surface with phase=repair", () => {
    const events = [
      demoEvent({ event_type: "runway.repair_dispatched", phase: "repair", outcome: "success", summary: "Repair worker dispatched." }),
      demoEvent({ event_type: "runway.repair_result", phase: "repair", outcome: "success", summary: "Repair worker completed." })
    ];
    const timeline = projectTimeline(events);
    expect(timeline.some((entry) => entry.event_type === "runway.repair_dispatched")).toBe(true);
    expect(timeline.some((entry) => entry.event_type === "runway.repair_result")).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it passes (timeline is generic)**

Run: `bun test packages/lens-projectors/tests/repair.test.ts`
Expected: PASS if `projectTimeline` already passes through unknown event types. If FAIL, extend the projector to include `repair` phase events (additive change).

- [ ] **Step 3: Extend scenario format to support sequential worker responses**

The current scenario JSON shape (see `tests/waygent-scenarios/trivial-success.json`) declares one `provider_fixture` consumed for the single worker call. Repair flows need a second response on the retry attempt.

Extend `tests/waygent-scenarios/` runner (likely `runWaygentScenario` / `loadWaygentScenario`) to accept an optional `provider_fixture_sequence: Array<"fake-success" | "fake-verify-fail" | "fake-repair-success">` that overrides the single `provider_fixture` field. Each entry corresponds to the worker attempts in order.

Locate the scenario runner source (search for `runWaygentScenario` and `loadWaygentScenario` definitions, likely under `packages/testkit/` or `tests/integration/`). Add:

```ts
// In the scenario loader:
if (Array.isArray(scenario.provider_fixture_sequence)) {
  // use sequence per-attempt
}
```

And add a new fake-repair fixture that responds with a minimal-diff worker_result completing the previously-failed verification.

- [ ] **Step 4: Add scenario JSON**

Create `tests/waygent-scenarios/repair-from-verify-failure.json`:

```json
{
  "id": "repair-from-verify-failure",
  "title": "Verify failure dispatches repair worker, which fixes and yields apply-ready run",
  "provider_fixture_sequence": ["fake-success", "fake-repair-success"],
  "source_dirty_before_apply": false,
  "force_missing_checkpoint": false,
  "plan": "```yaml waygent-task\nid: task_repair\ntitle: Repair scenario\ndependencies: []\nfile_claims:\n  - path: README.md\n    mode: owned\nrisk: low\nverify:\n  - test -f README.md\n```",
  "expected": {
    "run_status": "completed",
    "apply_status": "ready",
    "safe_wave": ["task_repair"],
    "event_types_must_include": [
      "runway.worker_result",
      "runway.verification_result",
      "runway.repair_dispatched",
      "runway.repair_result",
      "runway.checkpoint_created"
    ]
  }
}
```

(The exact `verify` command must be one that the fake provider can fail on first attempt and pass on the second. Coordinate with the fake-repair fixture implementation.)

- [ ] **Step 5: Update scenario runner expected-shape**

If the existing scenarios test only checks `expected.event_types` for exact-equality, change the runner to also support `event_types_must_include` as a subset assertion (or convert the new scenario to the existing exact-list shape — generate the full sequence from a real run during fixture authoring).

Document the assertion mode used in `expectReplay`. Choose subset (`event_types_must_include`) for forward-compat with future event additions in the repair pipeline.

- [ ] **Step 4: Run integration tests**

Run: `bun run waygent:scenarios`
Expected: PASS — 8 tests (7 existing + 1 new).

- [ ] **Step 5: Run full check**

Run: `bun run check && bun run platform:demo`
Expected: All gates green.

- [ ] **Step 6: Commit**

```bash
git add packages/lens-projectors/tests/repair.test.ts tests/integration/waygent-scenarios.test.ts
git commit -m "test: integration coverage for repair_to_apply_ready scenario"
```

---

## Final Verification

- [ ] **Step 1: Full check from clean state**

Run from the repository root:
```bash
bun run check && bun run waygent:scenarios && bun run platform:demo && git diff --check
```
Expected: all green.

- [ ] **Step 2: Closeout summary**

Confirm:
- `worker_result.evidence.patch_ref` written for all completed workers in a sample run.
- `waygent repair --run <id> --dry-run` returns a sensible packet.
- Recovery flow on a synthetic verification failure dispatches a repair worker.
- Post-repair verify passes → checkpoint created → `waygent apply` works.

- [ ] **Step 3: Self-review checklist before declaring done**

Run `git log --oneline main..HEAD` and confirm the commit list reads:
1. `test(contracts): assert worker_result.evidence patch_ref shape`
2. `feat(orchestrator): add captureWorktreePatch helper for repair-base diff`
3. `feat(orchestrator): add repair WorkerRoleSlot with cheap-default role routing`
4. `feat(contracts): add WaygentRunStateV2.repair_budget for per-task repair attempts`
5. `feat(orchestrator): add buildRepairPacket with 16KB excerpt cap and evidence filter`
6. `feat(orchestrator): add selectRepairAction recovery selector with budget`
7. `feat(orchestrator): capture worktree diff into worker_result.evidence after each completed worker`
8. `feat(orchestrator): prepareRepairWorktree + repair branch hook in wave loop`
9. `feat(orchestrator): dispatch repair worker on verification_failed when patch_ref present`
10. `feat(cli): add waygent repair command with --task, --instruction, --evidence, --dry-run`
11. `test: integration coverage for repair_to_apply_ready scenario`

If any are missing or out of order, fix and re-stage before considering the plan complete.
