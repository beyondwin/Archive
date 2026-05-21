# Waygent Execution Reliability And Operator UX Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the execution-intelligence dogfood failure class by making Waygent own verification environment setup and failure classification, then expose cleaner operator evidence through CLI, API, console, plan scaffold, and a real dogfood run.

**Architecture:** Keep `waygent.run_state.v2` and AgentLens event JSONL as the source of truth. Add a verification environment layer before kernel execution, classify verification failures into existing `FailureClass` values, prefer state evidence in `explain/resume`, summarize provider stderr without hiding raw artifacts, and add a scaffold path for executable `waygent-task` plans. Treat artifact-index dogfood as final acceptance evidence, not optional polish.

**Tech Stack:** TypeScript, Bun test runner, `@waygent/contracts`, `@waygent/orchestrator`, `@waygent/provider-adapters`, `@waygent/lens-projectors`, `apps/cli`, `apps/api`, `apps/console`, filesystem JSON artifacts.

---

## Context

Relevant design:

- `docs/superpowers/specs/2026-05-22-waygent-execution-reliability-operator-ux-hardening-design.md`

Failure evidence from the previous run:

- First run failed because isolated worktree verification could not resolve `ajv` and `@vitejs/plugin-react`.
- Retry succeeded only after each verification command manually created and removed a `node_modules` symlink.
- `explain` returned an imprecise failure summary when v2 state had better evidence.
- event `occurred_at` values were fixed instead of runtime timestamps.
- artifact index and phase timing need dogfood evidence from the latest runtime.

Constraints:

- Do not weaken checkpoint manifests, digest checks, dry-run evidence, completion audit, reconciliation, or clean-checkout apply rules.
- Do not let provider-reported success override Waygent-owned kernel verification.
- Do not commit runtime state, `node_modules`, build outputs, provider transcripts, or `.DS_Store`.
- Do not restore AgentRunway or KWS executor routing.
- Keep live provider smoke tests opt-in.

## File Structure

- `packages/contracts/src/types.ts`: add provider log summary types and optional process evidence field.
- `packages/contracts/src/schemas.ts`: validate the provider log summary field in `ProviderProcessEvidence`.
- `packages/contracts/tests/contracts.test.ts`: contract coverage for provider log summary evidence.
- `packages/orchestrator/src/verificationEnvironment.ts`: prepare and clean verification-only dependency affordances.
- `packages/orchestrator/tests/verificationEnvironment.test.ts`: unit tests for symlink setup, cleanup, and disabled mode.
- `packages/orchestrator/src/verification.ts`: classify kernel verification failures and return structured failure evidence.
- `packages/orchestrator/tests/verification.test.ts`: unit tests for dependency missing, command not found, timeout, and default verification failure.
- `packages/orchestrator/src/taskExecutor.ts`: pass workspace into verification, store environment/classification evidence, and write precise failure classes to events/state.
- `packages/orchestrator/tests/taskExecutor.test.ts`: regression for completed provider plus dependency-missing verification becoming a blocked task.
- `packages/orchestrator/src/runEvents.ts`: use runtime timestamps by default while allowing deterministic test timestamps.
- `packages/orchestrator/tests/runCommands.test.ts`: update deterministic event tests.
- `packages/orchestrator/src/runCommands.ts`: make `explain` and `resume` prefer v2 blocked-task evidence.
- `packages/orchestrator/tests/runCommandsV2.test.ts`: regression for state-based `dependency_missing` explanation and resume action.
- `packages/provider-adapters/src/logSummary.ts`: classify provider stderr lines into operator-friendly buckets.
- `packages/provider-adapters/src/processAdapters.ts`: attach log summaries to process evidence while preserving raw stderr.
- `packages/provider-adapters/src/index.ts`: export the log summary helper.
- `packages/provider-adapters/tests/providerLogSummary.test.ts`: unit tests for repeated plugin, MCP, skill-loader, warning, and error lines.
- `apps/api/src/server.ts`: include provider log summaries in run details through existing state passthrough.
- `apps/api/tests/api.test.ts`: assert run detail exposes provider signal metadata.
- `apps/console/src/uiModel.ts`: expose provider log summaries and next-action evidence in the UI model.
- `apps/console/src/uiModel.test.ts`: model tests for provider signal summary and state-based failure class.
- `apps/console/src/App.tsx`: render compact provider signal and next-action sections.
- `apps/console/src/styles.css`: small dense console styles for the new evidence sections.
- `packages/orchestrator/src/planScaffold.ts`: generate reviewed `waygent-task` blocks from explicit fields.
- `packages/orchestrator/tests/planScaffold.test.ts`: unit coverage for scaffold output and missing field rejection.
- `apps/cli/src/index.ts`: expose `scaffold-plan`.
- `apps/cli/tests/cli.test.ts`: CLI parser and scaffold command tests.
- `skills/waygent/SKILL.md`: document scaffold use for wrapper-plan creation.
- `tests/waygent-scenarios/dependency-missing.json`: scenario fixture for classified dependency-missing verification.
- `tests/integration/waygent-scenarios.test.ts`: include the new scenario fixture.
- `packages/testkit/src/waygentScenarioHarness.ts`: normalize scenario task failure classes for golden replay assertions.
- `docs/operations/waygent.md`: document verification environment behavior and dogfood evidence expectations.

## Execution Order

Hard gate:

1. Task 1: provider log summary contract.
2. Task 2: verification environment and failure classification.
3. Task 3: task executor, state-based explain/resume, and real event timestamps.

Do not start console UX, plan scaffold, or dogfood polish until Task 3 passes.

Parallel-safe after Task 3:

- Task 4 provider log summarization and Task 5 plan scaffold can run in parallel if workers keep file scopes separate.
- Task 6 API/console UX depends on Task 4 provider log evidence and Task 3 state-based explain behavior.
- Task 7 dogfood and docs must run last.

Shared-core files:

- `packages/orchestrator/src/taskExecutor.ts`, `packages/orchestrator/src/verification.ts`, and `packages/orchestrator/src/runCommands.ts` should be edited sequentially.

## Waygent Task Block For Execution

```yaml waygent-task
id: task_execution_reliability_operator_ux_hardening
title: Implement docs/superpowers/plans/2026-05-22-waygent-execution-reliability-operator-ux-hardening.md against docs/superpowers/specs/2026-05-22-waygent-execution-reliability-operator-ux-hardening-design.md. Land core verification environment hardening first, then provider log summaries, executable plan scaffold, console/API UX, and dogfood evidence without weakening apply readiness.
dependencies: []
file_claims:
  - path: packages/contracts/src/types.ts
    mode: owned
  - path: packages/contracts/src/schemas.ts
    mode: owned
  - path: packages/contracts/tests/contracts.test.ts
    mode: owned
  - path: packages/orchestrator/src/verificationEnvironment.ts
    mode: owned
  - path: packages/orchestrator/tests/verificationEnvironment.test.ts
    mode: owned
  - path: packages/orchestrator/src/verification.ts
    mode: owned
  - path: packages/orchestrator/tests/verification.test.ts
    mode: owned
  - path: packages/orchestrator/src/taskExecutor.ts
    mode: owned
  - path: packages/orchestrator/tests/taskExecutor.test.ts
    mode: owned
  - path: packages/orchestrator/src/runEvents.ts
    mode: owned
  - path: packages/orchestrator/tests/runCommands.test.ts
    mode: owned
  - path: packages/orchestrator/src/runCommands.ts
    mode: owned
  - path: packages/orchestrator/tests/runCommandsV2.test.ts
    mode: owned
  - path: packages/provider-adapters/src/logSummary.ts
    mode: owned
  - path: packages/provider-adapters/src/processAdapters.ts
    mode: owned
  - path: packages/provider-adapters/src/index.ts
    mode: owned
  - path: packages/provider-adapters/tests/providerLogSummary.test.ts
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
  - path: packages/orchestrator/src/planScaffold.ts
    mode: owned
  - path: packages/orchestrator/tests/planScaffold.test.ts
    mode: owned
  - path: apps/cli/src/index.ts
    mode: owned
  - path: apps/cli/tests/cli.test.ts
    mode: owned
  - path: skills/waygent/SKILL.md
    mode: owned
  - path: tests/waygent-scenarios/dependency-missing.json
    mode: owned
  - path: tests/integration/waygent-scenarios.test.ts
    mode: owned
  - path: packages/testkit/src/waygentScenarioHarness.ts
    mode: owned
  - path: docs/operations/waygent.md
    mode: owned
risk: high
verify:
  - bun test packages/contracts/tests/contracts.test.ts packages/orchestrator/tests/verificationEnvironment.test.ts packages/orchestrator/tests/verification.test.ts packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/tests/runCommands.test.ts packages/orchestrator/tests/runCommandsV2.test.ts packages/provider-adapters/tests/providerLogSummary.test.ts packages/orchestrator/tests/planScaffold.test.ts apps/cli/tests/cli.test.ts apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts
  - bun run check
  - bun run waygent:scenarios
  - bun run platform:demo
  - bun run check:legacy
  - bun run --cwd apps/console build
  - git diff --check
```

## Task 1: Add Provider Log Summary Contract

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/contracts/tests/contracts.test.ts`

- [ ] **Step 1: Write failing contract coverage**

In `packages/contracts/tests/contracts.test.ts`, update the existing worker/provider manifest contract test so the `ProviderAttempt.process` object includes:

```ts
      stderr_summary: {
        total_lines: 5,
        counts: {
          error: 1,
          warning: 1,
          mcp: 1,
          plugin_manifest: 1,
          skill_loader: 1,
          other: 0
        },
        samples: [
          { category: "error", line: "ERROR failed to load skill" },
          { category: "plugin_manifest", line: "ignoring interface.defaultPrompt" }
        ]
      }
```

- [ ] **Step 2: Verify the contract test fails**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
```

Expected: FAIL because `stderr_summary` is rejected by `providerProcessEvidenceSchema`.

- [ ] **Step 3: Add provider log summary types**

In `packages/contracts/src/types.ts`, add these types near `ProviderProcessEvidence`:

```ts
export type ProviderLogCategory =
  | "error"
  | "warning"
  | "mcp"
  | "plugin_manifest"
  | "skill_loader"
  | "other";

export interface ProviderLogSummary {
  total_lines: number;
  counts: Record<ProviderLogCategory, number>;
  samples: Array<{ category: ProviderLogCategory; line: string }>;
}
```

Then extend `ProviderProcessEvidence`:

```ts
  stderr_summary?: ProviderLogSummary;
```

- [ ] **Step 4: Add schema support**

In `packages/contracts/src/schemas.ts`, add `providerLogCategoryValues` near `providerRoleValues`:

```ts
const providerLogCategoryValues = ["error", "warning", "mcp", "plugin_manifest", "skill_loader", "other"] as const;
```

Add `providerLogSummarySchema` before `providerProcessEvidenceSchema`:

```ts
const providerLogSummarySchema = {
  type: "object",
  additionalProperties: false,
  required: ["total_lines", "counts", "samples"],
  properties: {
    total_lines: { type: "integer", minimum: 0 },
    counts: {
      type: "object",
      additionalProperties: false,
      required: providerLogCategoryValues,
      properties: Object.fromEntries(providerLogCategoryValues.map((category) => [category, { type: "integer", minimum: 0 }]))
    },
    samples: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["category", "line"],
        properties: {
          category: { enum: providerLogCategoryValues },
          line: { type: "string" }
        }
      }
    }
  }
} as const;
```

Add the optional property to `providerProcessEvidenceSchema.properties`:

```ts
    stderr_summary: providerLogSummarySchema
```

- [ ] **Step 5: Verify contracts**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/contracts/tests/contracts.test.ts
git commit -m "feat: add provider log summary contract"
```

## Task 2: Add Verification Environment And Failure Classification

**Files:**
- Create: `packages/orchestrator/src/verificationEnvironment.ts`
- Create: `packages/orchestrator/tests/verificationEnvironment.test.ts`
- Modify: `packages/orchestrator/src/verification.ts`
- Modify: `packages/orchestrator/tests/verification.test.ts`

- [ ] **Step 1: Add failing verification environment tests**

Create `packages/orchestrator/tests/verificationEnvironment.test.ts`:

```ts
import { existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { prepareVerificationEnvironment } from "../src/verificationEnvironment";

describe("verification environment", () => {
  test("links source node_modules into the worktree for verification and cleans it up", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-verify-env-source-"));
    const worktree = mkdtempSync(join(tmpdir(), "waygent-verify-env-worktree-"));
    mkdirSync(join(workspace, "node_modules"));
    writeFileSync(join(workspace, "node_modules", ".keep"), "source dependency marker\n");

    const prepared = prepareVerificationEnvironment({ workspace, worktree });
    expect(prepared.evidence.status).toBe("prepared");
    expect(prepared.evidence.strategy).toBe("inherit_node_modules");
    expect(existsSync(join(worktree, "node_modules"))).toBe(true);

    prepared.cleanup();
    expect(existsSync(join(worktree, "node_modules"))).toBe(false);
  });

  test("does not overwrite an existing worktree node_modules", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-verify-env-source-"));
    const worktree = mkdtempSync(join(tmpdir(), "waygent-verify-env-worktree-"));
    mkdirSync(join(workspace, "node_modules"));
    mkdirSync(join(worktree, "node_modules"));

    const prepared = prepareVerificationEnvironment({ workspace, worktree });
    expect(prepared.evidence.status).toBe("skipped");
    expect(prepared.evidence.reason).toBe("worktree_node_modules_exists");
    prepared.cleanup();
    expect(existsSync(join(worktree, "node_modules"))).toBe(true);
  });

  test("records cleanup failures without throwing from cleanup", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-verify-env-source-"));
    const worktree = mkdtempSync(join(tmpdir(), "waygent-verify-env-worktree-"));
    mkdirSync(join(workspace, "node_modules"));
    const prepared = prepareVerificationEnvironment({ workspace, worktree });
    rmSync(join(worktree, "node_modules"), { force: true, recursive: true });
    symlinkSync(join(workspace, "node_modules"), join(worktree, "node_modules"));
    prepared.cleanup();
    expect(prepared.evidence.cleanup_status).toBe("removed");
  });
});
```

- [ ] **Step 2: Add failing verification classification tests**

Extend `packages/orchestrator/tests/verification.test.ts`:

```ts
  test("classifies missing package verification output as dependency_missing", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "waygent-verify-"));
    const result = await runVerificationCommands({
      run_id: "run_verify",
      task_id: "task_verify",
      cwd,
      commands: ["node -e \"throw new Error('Cannot find package ajv from validate.ts')\""]
    });

    expect(result.status).toBe("failed");
    expect(result.failure_class).toBe("dependency_missing");
    expect(result.failure_summary).toContain("Cannot find package");
  });

  test("classifies missing command verification output as command_not_found", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "waygent-verify-"));
    const result = await runVerificationCommands({
      run_id: "run_verify",
      task_id: "task_verify",
      cwd,
      commands: ["definitely-not-a-waygent-command"]
    });

    expect(result.status).toBe("failed");
    expect(result.failure_class).toBe("command_not_found");
  });
```

- [ ] **Step 3: Verify tests fail**

Run:

```bash
bun test packages/orchestrator/tests/verificationEnvironment.test.ts packages/orchestrator/tests/verification.test.ts
```

Expected: FAIL because the new module and output fields do not exist.

- [ ] **Step 4: Implement verification environment**

Create `packages/orchestrator/src/verificationEnvironment.ts`:

```ts
import { existsSync, rmSync, symlinkSync } from "node:fs";
import { join } from "node:path";

export interface VerificationEnvironmentEvidence {
  status: "prepared" | "skipped" | "failed";
  strategy: "inherit_node_modules" | "none";
  created_paths: string[];
  cleanup_status: "not_needed" | "pending" | "removed" | "failed";
  reason: string | null;
}

export interface PreparedVerificationEnvironment {
  evidence: VerificationEnvironmentEvidence;
  cleanup(): void;
}

export function prepareVerificationEnvironment(input: {
  workspace: string;
  worktree: string;
  disabled?: boolean;
}): PreparedVerificationEnvironment {
  const sourceNodeModules = join(input.workspace, "node_modules");
  const worktreeNodeModules = join(input.worktree, "node_modules");
  const evidence: VerificationEnvironmentEvidence = {
    status: "skipped",
    strategy: "none",
    created_paths: [],
    cleanup_status: "not_needed",
    reason: null
  };

  if (input.disabled) {
    evidence.reason = "disabled";
    return { evidence, cleanup: () => {} };
  }
  if (!existsSync(sourceNodeModules)) {
    evidence.reason = "source_node_modules_missing";
    return { evidence, cleanup: () => {} };
  }
  if (existsSync(worktreeNodeModules)) {
    evidence.reason = "worktree_node_modules_exists";
    return { evidence, cleanup: () => {} };
  }

  try {
    symlinkSync(sourceNodeModules, worktreeNodeModules, "dir");
    evidence.status = "prepared";
    evidence.strategy = "inherit_node_modules";
    evidence.created_paths = ["node_modules"];
    evidence.cleanup_status = "pending";
  } catch (error) {
    evidence.status = "failed";
    evidence.reason = error instanceof Error ? error.message : String(error);
    evidence.cleanup_status = "not_needed";
  }

  return {
    evidence,
    cleanup() {
      if (evidence.cleanup_status !== "pending") return;
      try {
        rmSync(worktreeNodeModules, { force: true, recursive: true });
        evidence.cleanup_status = "removed";
      } catch (error) {
        evidence.cleanup_status = "failed";
        evidence.reason = error instanceof Error ? error.message : String(error);
      }
    }
  };
}
```

- [ ] **Step 5: Extend verification output and classifier**

In `packages/orchestrator/src/verification.ts`, import `FailureClass` and define:

```ts
export interface VerificationFailureEvidence {
  failure_class: FailureClass | null;
  failure_summary: string | null;
  failed_verification_id: string | null;
}
```

Extend `VerificationRunOutput`:

```ts
  failure_class: FailureClass | null;
  failure_summary: string | null;
  failed_verification_id: string | null;
```

After collecting results, classify the first failed result:

```ts
const failed = results.find((result) => result.exit_code !== 0 || result.timed_out) ?? null;
const classified = failed ? classifyVerificationResult(failed) : null;
return {
  status: failed ? "failed" : "passed",
  results,
  failure_class: classified?.failure_class ?? null,
  failure_summary: classified?.failure_summary ?? null,
  failed_verification_id: failed?.request_id ?? null
};
```

Add the exported classifier:

```ts
export function classifyVerificationResult(result: KernelExecutionResult): {
  failure_class: FailureClass;
  failure_summary: string;
} {
  const text = `${result.stderr}\n${result.stdout}`;
  if (result.timed_out) return { failure_class: "timeout", failure_summary: "verification timed out" };
  if (/Cannot find package|ERR_MODULE_NOT_FOUND|Cannot find module/i.test(text)) {
    return { failure_class: "dependency_missing", failure_summary: firstSignalLine(text) };
  }
  if (/\bcommand not found\b|^not found\b/im.test(text)) {
    return { failure_class: "command_not_found", failure_summary: firstSignalLine(text) };
  }
  if (/permission denied|policy denied/i.test(text)) return { failure_class: "permission_denied", failure_summary: firstSignalLine(text) };
  return { failure_class: "verification_failed", failure_summary: firstSignalLine(text) };
}

function firstSignalLine(text: string): string {
  return text.split(/\r?\n/).map((line) => line.trim()).find(Boolean) ?? "verification failed";
}
```

- [ ] **Step 6: Verify Task 2**

Run:

```bash
bun test packages/orchestrator/tests/verificationEnvironment.test.ts packages/orchestrator/tests/verification.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add packages/orchestrator/src/verificationEnvironment.ts packages/orchestrator/tests/verificationEnvironment.test.ts packages/orchestrator/src/verification.ts packages/orchestrator/tests/verification.test.ts
git commit -m "feat: classify Waygent verification environment failures"
```

## Task 3: Wire Core Reliability Into Task Execution, Explain, Resume, And Events

**Files:**
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/tests/taskExecutor.test.ts`
- Modify: `packages/orchestrator/src/runEvents.ts`
- Modify: `packages/orchestrator/tests/runCommands.test.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/orchestrator/tests/runCommandsV2.test.ts`

- [ ] **Step 1: Add failing task executor regression**

In `packages/orchestrator/tests/taskExecutor.test.ts`, add a test using `provider: "fake"` and a verification command that imports a missing module:

```ts
  test("blocks completed provider work when Waygent verification reports dependency_missing", async () => {
    const workspace = initSourceCheckout("waygent-task-executor-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-task-executor-root-"));
    const parsed = parseWaygentPlan([
      "```yaml waygent-task",
      "id: task_dependency_missing",
      "title: Create file with missing dependency verification",
      "dependencies: []",
      "file_claims:",
      "  - path: dep.txt",
      "    mode: owned",
      "risk: low",
      "verify:",
      "  - node -e \"throw new Error('Cannot find package ajv from validate.ts')\"",
      "```"
    ].join("\n"));

    const result = await executeWaygentTask({
      root,
      run_id: "run_dependency_missing",
      workspace,
      worktree_root: join(root, "worktrees"),
      task: parsed.tasks[0]!,
      checkpoint_inputs: [],
      spec: null,
      provider: "fake",
      provider_processes: {}
    });

    expect(result.status).toBe("blocked");
    expect(result.latest_failure_class).toBe("dependency_missing");
    expect(result.events.find((event) => event.event_type === "runway.verification_result")?.payload).toMatchObject({
      failure_class: "dependency_missing"
    });
  });
```

- [ ] **Step 2: Add failing explain/resume regression**

In `packages/orchestrator/tests/runCommandsV2.test.ts`, add a blocked v2 state with no failure events and `latest_failure_class: "dependency_missing"`. Assert:

```ts
expect(explainRun({ root, run: "run_dependency_missing" })).toMatchObject({
  run_id: "run_dependency_missing",
  blocked_by: "dependency_missing"
});
expect(explainRun({ root, run: "run_dependency_missing" }).summary).toContain("dependency_missing");
expect(resumeRun({ root, run: "run_dependency_missing", dry_run: true }).allowed_actions).toEqual(["rerun_verification"]);
```

- [ ] **Step 3: Add failing runtime timestamp regression**

In `packages/orchestrator/tests/runCommands.test.ts`, replace the existing fixed timestamp assertion with:

```ts
const event = buildRunEvent({
  run_id: "run_next_event",
  sequence: 1,
  event_type: "platform.run_started",
  phase: "platform",
  outcome: "running",
  summary: "Run opened.",
  payload: {},
  occurred_at: "2026-05-21T00:00:00Z"
});
expect(event.occurred_at).toBe("2026-05-21T00:00:00Z");
expect(buildRunEvent({
  run_id: "run_runtime_time",
  sequence: 1,
  event_type: "platform.run_started",
  phase: "platform",
  outcome: "running",
  summary: "Run opened.",
  payload: {}
}).occurred_at).not.toBe("2026-05-21T00:00:00Z");
```

- [ ] **Step 4: Verify regressions fail**

Run:

```bash
bun test packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/tests/runCommands.test.ts packages/orchestrator/tests/runCommandsV2.test.ts
```

Expected: FAIL because task execution still emits `verification_failed`, `buildRunEvent` has no `occurred_at` input, or `explainRun` ignores state failure evidence.

- [ ] **Step 5: Wire verification environment into task execution**

In `packages/orchestrator/src/taskExecutor.ts`, import `prepareVerificationEnvironment`. Before `runVerificationCommands`, call:

```ts
const verificationEnvironment = prepareVerificationEnvironment({
  workspace: input.workspace,
  worktree: taskWorktree.path,
  disabled: process.env.WAYGENT_DISABLE_VERIFICATION_ENV === "1"
});
```

Wrap verification in `try/finally`:

```ts
let verification;
try {
  verification = await runVerificationCommands({
    run_id: input.run_id,
    task_id: input.task.id,
    cwd: taskWorktree.path,
    commands
  });
} finally {
  verificationEnvironment.cleanup();
}
```

When building `verificationRecords`, attach environment evidence:

```ts
      verification_environment: verificationEnvironment.evidence,
      failure_class: kernel.exit_code === 0 && !kernel.timed_out ? null : verification.failure_class
```

Set event payload and task failure class from `verification.failure_class`:

```ts
const verificationFailureClass = verification.failure_class ?? (verificationPassed ? null : worker.failure_class ?? "verification_failed");
...
payload: {
  task_id: input.task.id,
  failure_class: verificationFailureClass,
  failure_summary: verification.failure_summary,
  worker,
  verification: verificationRecords,
  checkpoint_ref: null
}
...
let latestFailureClass: FailureClass | null = verificationPassed ? null : verificationFailureClass ?? "verification_failed";
```

If `verificationEnvironment.evidence.status === "failed"`, skip command execution by treating the task as blocked with `environment_blocker`.

- [ ] **Step 6: Update run event input**

In `packages/orchestrator/src/runEvents.ts`, add `occurred_at?: string` to `RunEventInput` and set:

```ts
    occurred_at: input.occurred_at ?? new Date().toISOString(),
```

- [ ] **Step 7: Make explain prefer v2 state**

In `packages/orchestrator/src/runCommands.ts`, add a helper:

```ts
function blockedTaskFailure(state: WaygentRunStateV2): { task_id: string; failure_class: FailureClass | "unknown" } | null {
  const task = Object.values(state.tasks).find((candidate) =>
    (candidate.status === "blocked" || candidate.status === "failed" || state.status === "blocked") &&
    typeof candidate.latest_failure_class === "string" &&
    candidate.latest_failure_class.length > 0
  );
  if (!task?.latest_failure_class) return null;
  return { task_id: task.id, failure_class: task.latest_failure_class as FailureClass | "unknown" };
}
```

Use that helper before event failure projection in `explainRun`, and keep the cost hotspot summary:

```ts
const stateFailure = blockedTaskFailure(stateResult.state);
const activeFailure = stateFailure ?? failure;
...
blocked_by: activeFailure?.failure_class ?? null
```

In `resumeRun`, allow dependency/environment failures to rerun verification:

```ts
if (blockedTask.latest_failure_class === "dependency_missing" || blockedTask.latest_failure_class === "environment_blocker") {
  return { run_id: explanation.run_id, allowed_actions: ["rerun_verification"], dry_run: options.dry_run ?? false };
}
```

- [ ] **Step 8: Verify Task 3 and core gate**

Run:

```bash
bun test packages/orchestrator/tests/verificationEnvironment.test.ts packages/orchestrator/tests/verification.test.ts packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/tests/runCommands.test.ts packages/orchestrator/tests/runCommandsV2.test.ts
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```bash
git add packages/orchestrator/src/taskExecutor.ts packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/src/runEvents.ts packages/orchestrator/tests/runCommands.test.ts packages/orchestrator/src/runCommands.ts packages/orchestrator/tests/runCommandsV2.test.ts
git commit -m "feat: make Waygent explain verification blockers"
```

## Task 4: Summarize Provider Log Noise Without Hiding Raw Evidence

**Files:**
- Create: `packages/provider-adapters/src/logSummary.ts`
- Create: `packages/provider-adapters/tests/providerLogSummary.test.ts`
- Modify: `packages/provider-adapters/src/processAdapters.ts`
- Modify: `packages/provider-adapters/src/index.ts`
- Modify: `packages/provider-adapters/tests/codexAdapter.test.ts`
- Modify: `packages/provider-adapters/tests/claudeAdapter.test.ts`

- [ ] **Step 1: Write failing log summary tests**

Create `packages/provider-adapters/tests/providerLogSummary.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { summarizeProviderStderr } from "../src/logSummary";

describe("provider log summary", () => {
  test("groups repeated provider stderr noise into stable categories", () => {
    const summary = summarizeProviderStderr([
      "ERROR codex_core::session: failed to load skill /bad/SKILL.md",
      "WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt",
      "WARN codex_core_skills::loader: ignoring interface.icon_small",
      "WARN codex_mcp::rmcp_client: failed to initialize MCP client during shutdown",
      "WARN something else",
      "plain line"
    ].join("\n"));

    expect(summary.total_lines).toBe(6);
    expect(summary.counts).toMatchObject({
      error: 1,
      warning: 1,
      mcp: 1,
      plugin_manifest: 1,
      skill_loader: 1,
      other: 1
    });
    expect(summary.samples.map((sample) => sample.category)).toEqual(
      expect.arrayContaining(["error", "plugin_manifest", "skill_loader", "mcp"])
    );
  });
});
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
bun test packages/provider-adapters/tests/providerLogSummary.test.ts
```

Expected: FAIL because `logSummary.ts` does not exist.

- [ ] **Step 3: Implement log summary helper**

Create `packages/provider-adapters/src/logSummary.ts`:

```ts
import type { ProviderLogCategory, ProviderLogSummary } from "@waygent/contracts";

const categories: ProviderLogCategory[] = ["error", "warning", "mcp", "plugin_manifest", "skill_loader", "other"];

export function summarizeProviderStderr(stderr: string, sampleLimit = 8): ProviderLogSummary {
  const counts = Object.fromEntries(categories.map((category) => [category, 0])) as Record<ProviderLogCategory, number>;
  const samples: ProviderLogSummary["samples"] = [];
  const lines = stderr.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  for (const line of lines) {
    const category = categorizeProviderLogLine(line);
    counts[category] += 1;
    if (samples.length < sampleLimit && !samples.some((sample) => sample.category === category && sample.line === line)) {
      samples.push({ category, line });
    }
  }
  return { total_lines: lines.length, counts, samples };
}

export function categorizeProviderLogLine(line: string): ProviderLogCategory {
  if (/ERROR/i.test(line)) return "error";
  if (/mcp|rmcp/i.test(line)) return "mcp";
  if (/manifest|defaultPrompt|plugin/i.test(line)) return "plugin_manifest";
  if (/skill|SKILL\.md|codex_core_skills/i.test(line)) return "skill_loader";
  if (/WARN|warning/i.test(line)) return "warning";
  return "other";
}
```

- [ ] **Step 4: Attach summary to process evidence**

In `packages/provider-adapters/src/processAdapters.ts`, import the helper and update `withProcessEvidence`:

```ts
import { summarizeProviderStderr } from "./logSummary";
...
      stderr_summary: summarizeProviderStderr(output.stderr),
```

In `packages/provider-adapters/src/index.ts`, export it:

```ts
export * from "./logSummary";
```

- [ ] **Step 5: Update adapter tests**

In `packages/provider-adapters/tests/codexAdapter.test.ts` and `packages/provider-adapters/tests/claudeAdapter.test.ts`, add assertions to existing process-evidence tests:

```ts
expect(result.process?.stderr_summary?.counts).toBeTruthy();
expect(result.process?.stderr_summary?.total_lines).toBeGreaterThanOrEqual(0);
```

- [ ] **Step 6: Verify Task 4**

Run:

```bash
bun test packages/provider-adapters/tests/providerLogSummary.test.ts packages/provider-adapters/tests/codexAdapter.test.ts packages/provider-adapters/tests/claudeAdapter.test.ts packages/contracts/tests/contracts.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add packages/provider-adapters/src/logSummary.ts packages/provider-adapters/tests/providerLogSummary.test.ts packages/provider-adapters/src/processAdapters.ts packages/provider-adapters/src/index.ts packages/provider-adapters/tests/codexAdapter.test.ts packages/provider-adapters/tests/claudeAdapter.test.ts
git commit -m "feat: summarize Waygent provider logs"
```

## Task 5: Add Executable Plan Scaffold

**Files:**
- Create: `packages/orchestrator/src/planScaffold.ts`
- Create: `packages/orchestrator/tests/planScaffold.test.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Modify: `apps/cli/src/index.ts`
- Modify: `apps/cli/tests/cli.test.ts`
- Modify: `skills/waygent/SKILL.md`

- [ ] **Step 1: Write failing scaffold tests**

Create `packages/orchestrator/tests/planScaffold.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { scaffoldWaygentTask } from "../src/planScaffold";
import { parseWaygentPlan } from "../src/planParser";

describe("Waygent plan scaffold", () => {
  test("creates an executable waygent-task block from explicit fields", () => {
    const markdown = scaffoldWaygentTask({
      id: "task_reliability",
      title: "Implement reliability hardening",
      dependencies: [],
      file_claims: [
        { path: "packages/orchestrator/src/verification.ts", mode: "owned" },
        { path: "packages/orchestrator/tests/verification.test.ts", mode: "owned" }
      ],
      risk: "high",
      verify: ["bun test packages/orchestrator/tests/verification.test.ts"]
    });

    expect(markdown).toContain("```yaml waygent-task");
    expect(parseWaygentPlan(markdown).tasks[0]).toMatchObject({
      id: "task_reliability",
      risk: "high"
    });
  });

  test("rejects scaffold requests without explicit file claims", () => {
    expect(() => scaffoldWaygentTask({
      id: "task_bad",
      title: "Bad scaffold",
      dependencies: [],
      file_claims: [],
      risk: "low",
      verify: ["printf bad"]
    })).toThrow("file claims required");
  });
});
```

- [ ] **Step 2: Add failing CLI test**

In `apps/cli/tests/cli.test.ts`, add:

```ts
test("scaffold-plan emits executable waygent-task markdown", async () => {
  const result = await runCli([
    "scaffold-plan",
    "--id", "task_cli_scaffold",
    "--title", "CLI scaffold",
    "--claim", "README.md:owned",
    "--risk", "low",
    "--verify", "printf hello"
  ]);
  expect(String((result as { markdown: string }).markdown)).toContain("```yaml waygent-task");
});
```

- [ ] **Step 3: Verify scaffold tests fail**

Run:

```bash
bun test packages/orchestrator/tests/planScaffold.test.ts apps/cli/tests/cli.test.ts
```

Expected: FAIL because scaffold support does not exist.

- [ ] **Step 4: Implement scaffold helper**

Create `packages/orchestrator/src/planScaffold.ts`:

```ts
import type { RiskLevel } from "@waygent/contracts";
import type { FileClaim, FileClaimMode } from "@waygent/runway-control";

export interface ScaffoldWaygentTaskInput {
  id: string;
  title: string;
  dependencies: string[];
  file_claims: FileClaim[];
  risk: RiskLevel;
  verify: string[];
}

export function scaffoldWaygentTask(input: ScaffoldWaygentTaskInput): string {
  if (!input.id.trim()) throw new Error("task id required");
  if (!input.title.trim()) throw new Error("title required");
  if (input.file_claims.length === 0) throw new Error("file claims required");
  if (input.verify.length === 0) throw new Error("verification commands required");
  return [
    "```yaml waygent-task",
    `id: ${input.id}`,
    `title: ${input.title}`,
    `dependencies: [${input.dependencies.join(", ")}]`,
    "file_claims:",
    ...input.file_claims.flatMap((claim) => [`  - path: ${claim.path}`, `    mode: ${claim.mode}`]),
    `risk: ${input.risk}`,
    "verify:",
    ...input.verify.map((command) => `  - ${command}`),
    "```",
    ""
  ].join("\n");
}

export function parseClaimFlag(value: string): FileClaim {
  const [path, mode = "owned"] = value.split(":");
  if (!path) throw new Error("claim path required");
  if (!["owned", "shared_append", "read_only"].includes(mode)) throw new Error(`invalid claim mode ${mode}`);
  return { path, mode: mode as FileClaimMode };
}
```

Export it from `packages/orchestrator/src/index.ts`.

- [ ] **Step 5: Wire CLI command**

In `apps/cli/src/index.ts`, import `scaffoldWaygentTask` and `parseClaimFlag`. Add command handling before run/status branches:

```ts
if (parsed.command === "scaffold-plan") {
  const claims = valuesForFlag(argv, "--claim").map(parseClaimFlag);
  const verify = valuesForFlag(argv, "--verify");
  return {
    markdown: scaffoldWaygentTask({
      id: String(parsed.flags.id ?? ""),
      title: String(parsed.flags.title ?? ""),
      dependencies: typeof parsed.flags.dependencies === "string" ? String(parsed.flags.dependencies).split(",").filter(Boolean) : [],
      file_claims: claims,
      risk: parsed.flags.risk === "medium" || parsed.flags.risk === "high" ? parsed.flags.risk : "low",
      verify
    })
  };
}
```

Add helper:

```ts
function valuesForFlag(argv: string[], flag: string): string[] {
  const values: string[] = [];
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === flag && argv[index + 1] && !argv[index + 1]!.startsWith("--")) values.push(argv[index + 1]!);
  }
  return values;
}
```

- [ ] **Step 6: Update Waygent skill docs**

In `skills/waygent/SKILL.md`, add a default mapping:

```md
- "실행 가능한 waygent-task 만들어줘" ->
  `waygent scaffold-plan --id <task_id> --title <title> --claim <path:mode> --risk <low|medium|high> --verify <command>`
```

Add a stop rule:

```md
- If scaffold inputs do not include explicit file claims, risk, and verification commands, ask for those fields instead of inferring apply-capable write scope from prose.
```

- [ ] **Step 7: Verify Task 5**

Run:

```bash
bun test packages/orchestrator/tests/planScaffold.test.ts apps/cli/tests/cli.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

```bash
git add packages/orchestrator/src/planScaffold.ts packages/orchestrator/tests/planScaffold.test.ts packages/orchestrator/src/index.ts apps/cli/src/index.ts apps/cli/tests/cli.test.ts skills/waygent/SKILL.md
git commit -m "feat: scaffold executable Waygent plans"
```

## Task 6: Surface Operator Evidence In API And Console

**Files:**
- Modify: `apps/api/src/server.ts`
- Modify: `apps/api/tests/api.test.ts`
- Modify: `apps/console/src/uiModel.ts`
- Modify: `apps/console/src/uiModel.test.ts`
- Modify: `apps/console/src/App.tsx`
- Modify: `apps/console/src/styles.css`

- [ ] **Step 1: Add failing API test**

In `apps/api/tests/api.test.ts`, extend the real v2 run detail fixture to include `provider_attempts[0].process.stderr_summary`. Assert:

```ts
expect(detail.state.provider_attempts[0].process.stderr_summary.counts.plugin_manifest).toBeGreaterThanOrEqual(1);
expect(detail.execution_explanation.recommended_next_actions).toBeArray();
```

- [ ] **Step 2: Add failing console model test**

In `apps/console/src/uiModel.test.ts`, add a detail response containing:

```ts
provider_attempts: [
  {
    attempt_id: "attempt_task_a_1",
    task_id: "task_a",
    provider: "codex",
    process: {
      stderr_summary: {
        total_lines: 2,
        counts: { error: 0, warning: 1, mcp: 0, plugin_manifest: 1, skill_loader: 0, other: 0 },
        samples: [{ category: "plugin_manifest", line: "ignoring interface.defaultPrompt" }]
      }
    }
  }
]
```

Assert the UI model exposes:

```ts
expect(model.provider_log_summary?.total_lines).toBe(2);
expect(model.provider_log_summary?.counts.plugin_manifest).toBe(1);
```

- [ ] **Step 3: Verify API/model tests fail**

Run:

```bash
bun test apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts
```

Expected: FAIL because the console model does not expose provider signal metadata.

- [ ] **Step 4: Update UI model**

In `apps/console/src/uiModel.ts`, add a `provider_log_summary` field to the run detail model. Derive it from the first provider attempt with `process.stderr_summary`, using the exact summary shape from contracts.

Add a next-action field that uses `execution_explanation.recommended_next_actions[0]` when present.

- [ ] **Step 5: Render compact console evidence**

In `apps/console/src/App.tsx`, render a compact provider signal section near execution intelligence:

```tsx
{detail.provider_log_summary ? (
  <section className="evidence-panel">
    <h3>Provider Signals</h3>
    <div className="signal-grid">
      <span>Errors {detail.provider_log_summary.counts.error}</span>
      <span>Warnings {detail.provider_log_summary.counts.warning}</span>
      <span>Plugin {detail.provider_log_summary.counts.plugin_manifest}</span>
      <span>MCP {detail.provider_log_summary.counts.mcp}</span>
    </div>
  </section>
) : null}
```

In `apps/console/src/styles.css`, keep dense, non-card-nested styling:

```css
.signal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
  font-size: 12px;
}
```

- [ ] **Step 6: Verify Task 6**

Run:

```bash
bun test apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts
bun run --cwd apps/console build
```

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add apps/api/src/server.ts apps/api/tests/api.test.ts apps/console/src/uiModel.ts apps/console/src/uiModel.test.ts apps/console/src/App.tsx apps/console/src/styles.css
git commit -m "feat: show Waygent operator signals"
```

## Task 7: Add Dependency-Missing Scenario And Dogfood Evidence

**Files:**
- Create: `tests/waygent-scenarios/dependency-missing.json`
- Modify: `tests/integration/waygent-scenarios.test.ts`
- Modify: `packages/testkit/src/waygentScenarioHarness.ts`
- Modify: `docs/operations/waygent.md`

- [ ] **Step 1: Add scenario fixture**

Create `tests/waygent-scenarios/dependency-missing.json`:

```json
{
  "id": "dependency-missing",
  "title": "Dependency missing verification is classified",
  "provider_fixture": "fake-success",
  "source_dirty_before_apply": false,
  "force_missing_checkpoint": false,
  "plan": "```yaml waygent-task\nid: task_dependency_missing\ntitle: Dependency missing verification task\ndependencies: []\nfile_claims:\n  - path: dependency.txt\n    mode: owned\nrisk: low\nverify:\n  - node -e \"throw new Error('Cannot find package ajv from validate.ts')\"\n```",
  "expected": {
    "run_status": "failed",
    "apply_status": "not_ready",
    "total_events": 7,
    "safe_wave": ["task_dependency_missing"],
    "event_types": [
      "platform.run_started",
      "runway.plan_loaded",
      "runway.preflight_result",
      "runway.safe_wave_selected",
      "runway.worker_result",
      "runway.verification_result",
      "lens.trust_report_updated"
    ],
    "checkpoints": [],
    "combined_patch_ref": null,
    "failure_classes": ["dependency_missing"],
    "provider_attempts": [
      {
        "task_id": "task_dependency_missing",
        "provider": "fake",
        "stdout_ref": "artifacts/provider/attempt_task_dependency_missing_1.stdout.txt",
        "stderr_ref": "artifacts/provider/attempt_task_dependency_missing_1.stderr.txt",
        "worker_result_ref": "artifacts/worker/task_dependency_missing.json"
      }
    ]
  }
}
```

- [ ] **Step 2: Wire scenario harness**

The integration test already discovers every `tests/waygent-scenarios/*.json` file through `readdirSync`, so do not add an explicit scenario list.

In `packages/testkit/src/waygentScenarioHarness.ts`, add `failure_classes?: string[]` to both `WaygentScenarioExpectedReplay` and `NormalizedWaygentReplay`.

When normalizing a replay with state, set `normalized.failure_classes` from task-level state:

```ts
const failureClasses = failureClassesFromState(state);
if (failureClasses.length > 0) normalized.failure_classes = failureClasses;
```

Add the helper near `providerAttemptsFromState`:

```ts
function failureClassesFromState(state: WaygentRunStateV2): string[] {
  return uniqueStrings(
    Object.values(state.tasks ?? {})
      .map((task) => task.latest_failure_class)
      .filter((value): value is string => typeof value === "string" && value.length > 0)
  );
}
```

In `tests/integration/waygent-scenarios.test.ts`, extend `expectReplay`:

```ts
if (expected.failure_classes !== undefined) {
  expect(actual.failure_classes).toEqual(expected.failure_classes);
}
```

- [ ] **Step 3: Update operations docs**

In `docs/operations/waygent.md`, add a short section:

```md
## Verification Environment

Waygent prepares verification-only dependency access for isolated local worktrees. For Bun workspaces, a source `node_modules` directory may be temporarily linked into the task worktree during kernel verification and removed before checkpointing. If dependency access is unavailable, verification is blocked as `dependency_missing` or `environment_blocker` instead of `unknown`.
```

Add dogfood expectation:

```md
Before treating execution intelligence as complete, run a real Waygent dogfood execution and confirm `inspect` shows non-empty `artifact_index`, task `phase_timings`, real event timestamps, and precise `explain` blockers.
```

- [ ] **Step 4: Verify scenario and docs**

Run:

```bash
bun run waygent:scenarios
git diff --check
```

Expected: PASS.

- [ ] **Step 5: Run full verification**

Run:

```bash
bun run check
bun run platform:demo
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Dogfood latest runtime**

Use the Waygent CLI to run the task block in this plan against the design spec:

```bash
bun run apps/cli/src/index.ts run --provider codex --plan docs/superpowers/plans/2026-05-22-waygent-execution-reliability-operator-ux-hardening.md --spec docs/superpowers/specs/2026-05-22-waygent-execution-reliability-operator-ux-hardening-design.md --execution-mode multi-agent
```

After it completes, inspect the run:

```bash
bun run apps/cli/src/index.ts inspect --last --json
bun run apps/cli/src/index.ts explain --last
```

Expected evidence:

- `state.artifact_index.length > 0`;
- at least one task has `phase_timings`;
- event `occurred_at` values are real runtime timestamps;
- `explain` names a precise blocker or says no active failure barrier;
- no verification command has a hand-written `node_modules` symlink prefix.

- [ ] **Step 7: Commit Task 7**

```bash
git add tests/waygent-scenarios/dependency-missing.json tests/integration/waygent-scenarios.test.ts docs/operations/waygent.md
git commit -m "test: dogfood Waygent reliability evidence"
```

## Final Review Checklist

- [ ] `git status --short --branch --untracked-files=all` shows only intentional files before final staging.
- [ ] No runtime state, `node_modules`, `dist`, provider raw transcript, `.agentlens`, `.orchestrator`, `.codex-orchestrator`, or `.DS_Store` is staged.
- [ ] `bun run check` passes.
- [ ] `bun run waygent:scenarios` passes.
- [ ] `bun run platform:demo` reports trusted demo output.
- [ ] `bun run check:legacy` passes.
- [ ] `bun run --cwd apps/console build` passes.
- [ ] `git diff --check` passes.
- [ ] Dogfood `inspect` confirms artifact index and phase timing are present in a real run.
- [ ] Dogfood `explain` no longer reports `unknown` when v2 state has a precise failure class.
