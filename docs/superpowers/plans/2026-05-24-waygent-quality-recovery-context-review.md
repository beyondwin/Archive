# Waygent Quality Recovery Context Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Waygent recover executable plans automatically, keep coordinator context bounded, prevent false completion, integrate task recovery, and require review evidence when review mode is active.

**Architecture:** Extend the existing TypeScript Waygent runtime boundaries instead of adding a new framework. Intake changes stay in `planNormalizer` / `intakeRecovery`, context budgeting stays in `context-packer` plus `taskExecutor`, terminal completion invariants stay in orchestrator state finalization, retry policy integration stays in the scheduler loop, and review evidence gating stays in `completionAudit` / `reviewGate`.

**Tech Stack:** TypeScript, Bun test runner, `@waygent/orchestrator`, `@waygent/context-packer`, `@waygent/contracts`, Lens event artifacts.

---

## Context

**Spec:** `docs/superpowers/specs/2026-05-24-waygent-quality-recovery-context-review-design.md`

**Why this plan exists:** Recent local Waygent runs showed many blocked runs and one invalid terminal state:

```text
status=completed
lifecycle_outcome=finished
completion_audit.status=failed
```

This plan closes that class of quality failure while also reducing how much raw
context the main coordinator must carry.

**Execution mode:** Sequential. Each task modifies shared runtime contracts or
scheduler behavior, so task order matters.

**Plan safety:** The fenced `waygent-task` blocks use only safe verification
commands. Mutating maintenance commands such as Graphify refresh and git commit
belong to the operator after implementation, outside Waygent verification.

## File Structure

**New files:**

- `packages/orchestrator/tests/fixtures/memory_second_brain_plan.md` - regression fixture for Superpowers-style prose intake.
- `packages/orchestrator/src/contextBudgetGate.ts` - pure packet budget decision and shrink event payload builder.
- `packages/orchestrator/tests/contextBudgetGate.test.ts` - budget gate unit tests.
- `packages/orchestrator/src/terminalInvariant.ts` - single terminal state guard for completion audit invariants.
- `packages/orchestrator/tests/terminalInvariant.test.ts` - invalid terminal state unit tests.
- `packages/orchestrator/src/taskRecovery.ts` - scheduler-facing recovery decision and state record helper.
- `packages/orchestrator/tests/taskRecovery.test.ts` - recovery helper tests.
- `packages/orchestrator/src/reviewEvidence.ts` - review packet and review-required audit helper.
- `packages/orchestrator/tests/reviewEvidence.test.ts` - review evidence gate tests.

**Modified files:**

- `packages/orchestrator/src/planAdapters/verificationPolicy.ts` - classify install, formatter, codegen, Graphify, and git mutation as implementation-only.
- `packages/orchestrator/src/planNormalizer.ts` - preserve implementation-only command instructions while keeping `verify` safe.
- `packages/orchestrator/src/intakeRecovery.ts` - recover memory-second-brain-style plans without decision prompts when commands are safe.
- `packages/orchestrator/tests/planNormalizer.test.ts` - regression coverage for safe normalization.
- `packages/orchestrator/tests/intakeRecovery.test.ts` - regression coverage for recovered intake reports.
- `packages/context-packer/src/taskPacket.ts` - expose configurable context budget metadata needed by the gate.
- `packages/context-packer/tests/taskPacket.test.ts` - budget status coverage.
- `packages/contracts/src/types.ts` - add recovery failure classes and optional review/context fields.
- `packages/contracts/src/schemas.ts` - schema parity for new contract fields.
- `packages/contracts/tests/contracts.test.ts` - contract validation coverage.
- `packages/orchestrator/src/taskExecutor.ts` - block red packets before provider dispatch and emit handoff/context events.
- `packages/orchestrator/src/orchestrator.ts` - integrate recovery loop, terminal invariant guard, and review evidence handoff.
- `packages/orchestrator/src/completionAudit.ts` - require review evidence when configured.
- `packages/orchestrator/src/reviewGate.ts` - expand from predicate to evidence policy helpers.
- `packages/orchestrator/src/stateReconciliation.ts` - report invalid completed state as terminal drift.
- `packages/orchestrator/tests/taskExecutor.test.ts` - packet budget and event coverage.
- `packages/orchestrator/tests/orchestratorRunV2.test.ts` - end-to-end terminal state and recovery coverage.
- `docs/operations/plan-authoring.md` - document safe normalization behavior.
- `docs/operations/waygent.md` - document context budget, recovery, and review evidence gates.

---

## Task 1: Harden Intake Auto-Rewrite

```yaml waygent-task
id: task_1_harden_intake_auto_rewrite
title: Harden intake auto-rewrite
dependencies: []
file_claims:
  - path: packages/orchestrator/src/planAdapters/verificationPolicy.ts
    mode: owned
  - path: packages/orchestrator/src/planNormalizer.ts
    mode: owned
  - path: packages/orchestrator/src/intakeRecovery.ts
    mode: owned
  - path: packages/orchestrator/tests/fixtures/memory_second_brain_plan.md
    mode: owned
  - path: packages/orchestrator/tests/planNormalizer.test.ts
    mode: owned
  - path: packages/orchestrator/tests/intakeRecovery.test.ts
    mode: owned
  - path: packages/orchestrator/tests/verificationPolicy.test.ts
    mode: owned
  - path: docs/operations/plan-authoring.md
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/planNormalizer.test.ts packages/orchestrator/tests/intakeRecovery.test.ts packages/orchestrator/tests/verificationPolicy.test.ts
```

**Purpose:** A Superpowers-style plan with safe commands should normalize into
executable `waygent-task` YAML without asking the user to manually rewrite the
plan.

- [ ] **Step 1: Add the memory-second-brain fixture.**

Create `packages/orchestrator/tests/fixtures/memory_second_brain_plan.md`:

````markdown
# Memory Second Brain Implementation Plan

### Task 1: Add Memory Seed Command

**Files:**
- Modify: `package.json`
- Create: `scripts/memory/seed.mjs`

Run:

```bash
npm install
npm test -- --runInBand
npm run memory:validate
```

### Task 2: Add Memory Projection

**Files:**
- Modify: `src/memory/projector.ts`
- Modify: `src/memory/projector.test.ts`

Run:

```bash
npm run build
npm run validate
graphify update .
```
````

- [ ] **Step 2: Extend implementation-only command classification.**

In `packages/orchestrator/src/planAdapters/verificationPolicy.ts`, replace
`isImplementationOnlyCommand` with this rule set:

```typescript
function isImplementationOnlyCommand(segment: string): boolean {
  if (/^(npm|bun|pnpm|yarn)\s+install\b/.test(segment)) return true;
  if (/^(npm|bun|pnpm|yarn)\s+run\s+(format|fmt|generate|codegen)\b/.test(segment)) return true;
  if (/^prettier\s+--write\b/.test(segment)) return true;
  if (segment === "graphify update ." || segment.startsWith("graphify update ")) return true;
  return /^git\s+(add|commit|push|checkout|merge|rebase|stash|worktree|cherry-pick)\b/.test(segment);
}
```

Keep implementation-only commands classified as `ignored` unless they are
combined with a safe verification command in the same shell segment chain; that
mixed chain remains `unsafe` because verification would mutate tracked files.

- [ ] **Step 3: Add a normalizer regression test.**

Append this test to `packages/orchestrator/tests/planNormalizer.test.ts`:

```typescript
test("normalizes memory-second-brain style plans and strips implementation-only verify commands", () => {
  const fixture = readFileSync(join(import.meta.dir, "fixtures", "memory_second_brain_plan.md"), "utf8");
  const workspace = mkdtempSync(join(tmpdir(), "waygent-memory-plan-"));
  writeFileSync(join(workspace, "package.json"), JSON.stringify({
    scripts: {
      build: "vite build",
      validate: "astro check",
      "memory:validate": "node scripts/memory/validate.mjs"
    }
  }));

  const normalized = normalizeWaygentPlanInput({
    markdown: fixture,
    path: "/tmp/memory_second_brain.md",
    workspace
  });
  const parsed = parseWaygentPlan(normalized.markdown);

  expect(normalized.mode).toBe("superpowers");
  expect(parsed.tasks).toHaveLength(2);
  expect(parsed.tasks[0]?.verification_commands).toEqual([
    "npm test -- --runInBand",
    "npm run memory:validate"
  ]);
  expect(parsed.tasks[1]?.verification_commands).toEqual([
    "npm run build",
    "npm run validate"
  ]);
  expect(parsed.tasks[0]?.instructions.join("\n")).toContain("npm install");
  expect(parsed.tasks[1]?.instructions.join("\n")).toContain("graphify update .");
  expect(normalized.markdown).not.toContain("verify:\n  - npm install");
  expect(normalized.markdown).not.toContain("verify:\n  - graphify update .");
});
```

Add imports at the top of the test file:

```typescript
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
```

- [ ] **Step 4: Add intake recovery regression coverage.**

Append this test to `packages/orchestrator/tests/intakeRecovery.test.ts`:

```typescript
test("recovers memory-second-brain style plans without an operator decision", () => {
  const workspace = mkdtempSync(join(tmpdir(), "waygent-memory-recovery-"));
  writeFileSync(join(workspace, "package.json"), JSON.stringify({
    scripts: {
      build: "vite build",
      validate: "astro check",
      "memory:validate": "node scripts/memory/validate.mjs"
    }
  }));

  const recovered = recoverWaygentPlanInput({
    markdown: fixture("memory_second_brain_plan.md"),
    path: "/tmp/memory_second_brain.md",
    workspace,
    spec_markdown: "# Memory Second Brain\n",
    spec_path: "/tmp/memory_spec.md"
  });

  expect(recovered.status).toBe("recovered");
  expect(recovered.report.can_start).toBe(true);
  expect(recovered.report.question).toBeNull();
  expect(recovered.report.normalized_plan_ref).toBe("artifacts/intake/normalized-plan.md");
  expect(recovered.report.findings.some((finding) => finding.severity === "blocking")).toBe(false);
});
```

Update the existing `node:fs` import so it includes the new helpers, and add
the `node:os` import:

```typescript
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
```

- [ ] **Step 5: Make recovery use normalizer output when strict normalization succeeds after command filtering.**

In `packages/orchestrator/src/intakeRecovery.ts`, keep the strict
`normalizeWaygentPlanInput` path as the preferred result. When it returns
`mode="superpowers"`, set report status to `recovered`, not `not_needed`,
because Waygent changed the executable input:

```typescript
const status: WaygentIntakeRecovery["status"] =
  normalized.mode === "superpowers" ? "recovered" : "not_needed";
```

Use the same status in the returned top-level object and set
`normalized_plan_ref` to `artifacts/intake/normalized-plan.md` for recovered
plans.

- [ ] **Step 6: Document the safe rewrite behavior.**

In `docs/operations/plan-authoring.md`, add a short subsection under
`Verification Commands`:

```markdown
### Superpowers Plan Normalization

When a Superpowers-style implementation plan includes task headings, file
claims, and safe verification commands, Waygent normalizes it into executable
`yaml waygent-task` blocks during intake. Commands that install dependencies,
format files, generate code, update Graphify output, or mutate git state are
preserved as implementation instructions and removed from `verify`.

Waygent asks for a decision only when the command is destructive, escapes the
workspace, writes unclaimed files, or leaves a source-changing task without a
usable verification command.
```

- [ ] **Step 7: Run targeted verification.**

Run:

```bash
bun test packages/orchestrator/tests/planNormalizer.test.ts packages/orchestrator/tests/intakeRecovery.test.ts packages/orchestrator/tests/verificationPolicy.test.ts
```

Expected: PASS.

---

## Task 2: Gate Red Context Packets Before Provider Dispatch

```yaml waygent-task
id: task_2_gate_red_context_packets
title: Gate red context packets before provider dispatch
dependencies: [task_1_harden_intake_auto_rewrite]
file_claims:
  - path: packages/contracts/src/types.ts
    mode: owned
  - path: packages/contracts/src/schemas.ts
    mode: owned
  - path: packages/contracts/tests/contracts.test.ts
    mode: owned
  - path: packages/context-packer/src/taskPacket.ts
    mode: owned
  - path: packages/context-packer/tests/taskPacket.test.ts
    mode: owned
  - path: packages/orchestrator/src/contextBudgetGate.ts
    mode: owned
  - path: packages/orchestrator/src/taskExecutor.ts
    mode: owned
  - path: packages/orchestrator/tests/contextBudgetGate.test.ts
    mode: owned
  - path: packages/orchestrator/tests/taskExecutor.test.ts
    mode: owned
  - path: docs/operations/waygent.md
    mode: owned
risk: high
verify:
  - bun test packages/contracts/tests/contracts.test.ts packages/context-packer/tests/taskPacket.test.ts packages/orchestrator/tests/contextBudgetGate.test.ts packages/orchestrator/tests/taskExecutor.test.ts
```

**Purpose:** The coordinator must not dispatch a worker with an oversized task
packet. Red context packets become `context_missing` blockers with evidence
refs instead of hidden prompt bloat.

- [ ] **Step 1: Add failure classes and packet fields to contracts.**

In `packages/contracts/src/types.ts`, extend `FailureClass`:

```typescript
  | "context_missing"
  | "insufficient_context"
```

Extend `WaygentTaskPacket.context_budget`:

```typescript
  context_budget: {
    estimated_chars: number;
    max_chars: number;
    status: "green" | "yellow" | "red";
    shrink_actions?: string[];
  };
```

Mirror those changes in `packages/contracts/src/schemas.ts` by adding the two
failure class enum values and allowing optional `shrink_actions` as an array of
strings.

- [ ] **Step 2: Add contract validation test.**

In `packages/contracts/tests/contracts.test.ts`, add:

```typescript
test("task packet context budget can include shrink actions", () => {
  const packet = validateContract("waygent.task_packet.v1", {
    schema: "waygent.task_packet.v1",
    run_id: "run_context",
    task_id: "task_context",
    role: "implement",
    task_title: "Context task",
    plan_excerpt: "Do the work",
    spec_excerpt: "Spec section",
    file_claims: [],
    allowed_write_globs: [],
    forbidden_write_globs: [".git/**"],
    dependencies: [],
    checkpoint_inputs: [],
    acceptance_commands: ["printf hello"],
    verification_commands: ["printf hello"],
    risk: "low",
    previous_failures: [],
    decisions: [],
    context_budget: {
      estimated_chars: 120000,
      max_chars: 60000,
      status: "red",
      shrink_actions: ["replace_full_logs_with_digest"]
    },
    sha256: "abc123"
  });

  expect(packet.context_budget.status).toBe("red");
  expect(packet.context_budget.shrink_actions).toEqual(["replace_full_logs_with_digest"]);
});
```

- [ ] **Step 3: Add `contextBudgetGate.ts`.**

Create `packages/orchestrator/src/contextBudgetGate.ts`:

```typescript
import type { WaygentTaskPacket } from "@waygent/contracts";

export interface ContextBudgetDecision {
  status: "allow" | "warn" | "block";
  failure_class: "context_missing" | null;
  shrink_actions: string[];
  summary: string;
}

export function evaluateContextBudget(packet: WaygentTaskPacket): ContextBudgetDecision {
  const budget = packet.context_budget;
  if (budget.status === "green") {
    return { status: "allow", failure_class: null, shrink_actions: [], summary: "Task packet is within context budget." };
  }
  const shrink_actions = budget.shrink_actions ?? defaultShrinkActions();
  if (budget.status === "yellow") {
    return { status: "warn", failure_class: null, shrink_actions, summary: "Task packet is near context budget." };
  }
  return { status: "block", failure_class: "context_missing", shrink_actions, summary: "Task packet exceeds context budget." };
}

export function defaultShrinkActions(): string[] {
  return [
    "keep_task_owned_files_and_direct_dependencies",
    "replace_full_logs_with_verification_digests",
    "replace_full_spec_with_mapped_sections",
    "summarize_prior_failures",
    "request_operator_decision_if_still_red"
  ];
}
```

- [ ] **Step 4: Add context budget gate tests.**

Create `packages/orchestrator/tests/contextBudgetGate.test.ts`:

```typescript
import { describe, expect, test } from "bun:test";
import type { WaygentTaskPacket } from "@waygent/contracts";
import { evaluateContextBudget } from "../src/contextBudgetGate";

function packet(status: "green" | "yellow" | "red"): WaygentTaskPacket {
  return {
    schema: "waygent.task_packet.v1",
    run_id: "run",
    task_id: "task",
    role: "implement",
    task_title: "Task",
    plan_excerpt: "Plan",
    spec_excerpt: "Spec",
    file_claims: [],
    allowed_write_globs: [],
    forbidden_write_globs: [],
    dependencies: [],
    checkpoint_inputs: [],
    acceptance_commands: ["printf hello"],
    verification_commands: ["printf hello"],
    risk: "low",
    previous_failures: [],
    decisions: [],
    context_budget: { estimated_chars: 1, max_chars: 10, status },
    sha256: "hash"
  };
}

describe("evaluateContextBudget", () => {
  test("allows green packets", () => {
    expect(evaluateContextBudget(packet("green"))).toMatchObject({ status: "allow", failure_class: null });
  });

  test("warns on yellow packets", () => {
    expect(evaluateContextBudget(packet("yellow"))).toMatchObject({ status: "warn", failure_class: null });
  });

  test("blocks red packets with context_missing", () => {
    const decision = evaluateContextBudget(packet("red"));
    expect(decision.status).toBe("block");
    expect(decision.failure_class).toBe("context_missing");
    expect(decision.shrink_actions).toContain("replace_full_spec_with_mapped_sections");
  });
});
```

- [ ] **Step 5: Thread max packet size through task execution.**

In `packages/orchestrator/src/taskExecutor.ts`, extend
`ExecuteWaygentTaskInput`:

```typescript
  task_packet_max_chars?: number;
```

Pass that value into `buildTaskPacket`:

```typescript
    ...(input.task_packet_max_chars ? { max_chars: input.task_packet_max_chars } : {}),
```

- [ ] **Step 6: Block red packets before provider dispatch.**

In `taskExecutor.ts`, import the gate:

```typescript
import { evaluateContextBudget } from "./contextBudgetGate";
```

After writing the task packet artifact and before provider prompt dispatch,
evaluate the packet. Always emit `context.packet_budget_evaluated`; emit
`handoff.created` for green/yellow packets; return a blocked result for red
packets before calling the provider.

The blocked result should use:

```typescript
failure_class: "context_missing"
summary: "Task packet exceeds context budget."
```

and include event payload:

```typescript
{
  task_id: input.task.id,
  task_packet_ref: packetArtifact.path,
  task_packet_sha256: packetArtifact.sha256,
  context_budget: packet.context_budget,
  shrink_actions: decision.shrink_actions
}
```

Use the existing `hookDeniedResult` structure as the model for returning a
blocked `WaygentTaskExecutionResult` without provider execution.

- [ ] **Step 7: Add task executor regression.**

In `packages/orchestrator/tests/taskExecutor.test.ts`, add a test that calls
`executeWaygentTask` with `task_packet_max_chars: 500` and a large
`instructions` body. Assert:

```typescript
expect(result.status).toBe("blocked");
expect(result.latest_failure_class).toBe("context_missing");
expect(result.events.map((event) => event.event_type)).toContain("context.packet_budget_evaluated");
expect(result.events.map((event) => event.event_type)).not.toContain("runway.worker_result");
```

- [ ] **Step 8: Document context gate behavior.**

In `docs/operations/waygent.md`, add:

```markdown
### Context Budget Gate

Waygent evaluates each task packet before provider dispatch. Green packets
dispatch normally. Yellow packets dispatch with `context.packet_budget_evaluated`
evidence. Red packets do not dispatch; Waygent records `context_missing` and the
ordered shrink actions needed to make the handoff executable.
```

- [ ] **Step 9: Run targeted verification.**

Run:

```bash
bun test packages/contracts/tests/contracts.test.ts packages/context-packer/tests/taskPacket.test.ts packages/orchestrator/tests/contextBudgetGate.test.ts packages/orchestrator/tests/taskExecutor.test.ts
```

Expected: PASS.

---

## Task 3: Enforce Terminal Completion Invariant

```yaml waygent-task
id: task_3_enforce_terminal_completion_invariant
title: Enforce terminal completion invariant
dependencies: [task_2_gate_red_context_packets]
file_claims:
  - path: packages/orchestrator/src/terminalInvariant.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/src/stateReconciliation.ts
    mode: owned
  - path: packages/orchestrator/tests/terminalInvariant.test.ts
    mode: owned
  - path: packages/orchestrator/tests/orchestratorRunV2.test.ts
    mode: owned
  - path: packages/orchestrator/tests/stateReconciliation.test.ts
    mode: owned
risk: high
verify:
  - bun test packages/orchestrator/tests/terminalInvariant.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts packages/orchestrator/tests/stateReconciliation.test.ts
```

**Purpose:** `completed + failed completion_audit` must be impossible after any
terminal state write or reconciliation pass.

- [ ] **Step 1: Add terminal invariant helper.**

Create `packages/orchestrator/src/terminalInvariant.ts`:

```typescript
import type { WaygentRunStateV2 } from "@waygent/contracts";

export interface TerminalInvariantResult {
  passed: boolean;
  reason: string | null;
}

export function terminalCompletionInvariant(state: WaygentRunStateV2): TerminalInvariantResult {
  const audit = state.completion_audit as { status?: unknown; residual_risk?: unknown } | null;
  if (state.status !== "completed" && state.lifecycle_outcome !== "finished") {
    return { passed: true, reason: null };
  }
  if (audit?.status !== "passed") {
    return { passed: false, reason: "completed_with_failed_completion_audit" };
  }
  if (Array.isArray(audit.residual_risk) && audit.residual_risk.length > 0) {
    return { passed: false, reason: "completed_with_residual_risk" };
  }
  return { passed: true, reason: null };
}

export function blockInvalidTerminalCompletion(state: WaygentRunStateV2): TerminalInvariantResult {
  const result = terminalCompletionInvariant(state);
  if (result.passed) return result;
  state.status = "blocked";
  state.lifecycle_outcome = "blocked";
  state.current_phase = "complete";
  state.apply = { status: "blocked", reason: result.reason ?? "terminal_invariant_failed" };
  state.timestamps.updated_at = new Date().toISOString();
  state.timestamps.completed_at = state.timestamps.updated_at;
  return result;
}
```

- [ ] **Step 2: Add invariant tests.**

Create `packages/orchestrator/tests/terminalInvariant.test.ts` using the
existing `baseRunState` helper from `packages/orchestrator/tests/support`.
Cover:

```typescript
test("blocks completed state with failed audit", () => {
  const state = runStateFixture({
    status: "completed",
    lifecycle_outcome: "finished",
    completion_audit: { status: "failed", residual_risk: ["task_1:missing_checkpoint"] }
  });

  const result = blockInvalidTerminalCompletion(state);

  expect(result).toEqual({ passed: false, reason: "completed_with_failed_completion_audit" });
  expect(state.status).toBe("blocked");
  expect(state.lifecycle_outcome).toBe("blocked");
  expect(state.apply.reason).toBe("completed_with_failed_completion_audit");
});
```

Also add a passing test for `completion_audit.status="passed"` and empty
`residual_risk`.

- [ ] **Step 3: Guard orchestrator terminal writes.**

In `packages/orchestrator/src/orchestrator.ts`, import:

```typescript
import { blockInvalidTerminalCompletion } from "./terminalInvariant";
```

After `buildCompletionAudit`, keep the existing passed/blocked assignment, then
call the guard before flushing:

```typescript
const invariant = blockInvalidTerminalCompletion(state);
if (!invariant.passed) {
  state.recovery.push({
    task_id: null,
    failure_class: "terminal_rejected",
    action: "halt",
    attempt_number: 1,
    automatic: true,
    prior_summary: invariant.reason,
    result: "blocked",
    evidence_refs: []
  });
}
```

After reconciliation mutates `completion_audit.status`, call the guard again.
If it blocks, append `platform.invariant_violation` with:

```typescript
{
  failure_class: "terminal_rejected",
  reason: invariant.reason
}
```

- [ ] **Step 4: Strengthen reconciliation drift.**

In `packages/orchestrator/src/stateReconciliation.ts`, keep the existing
`completed run requires passed completion audit` check and add residual-risk
coverage:

```typescript
if (
  state.status === "completed" &&
  completionAudit?.status === "passed" &&
  Array.isArray((completionAudit as { residual_risk?: unknown }).residual_risk) &&
  ((completionAudit as { residual_risk: unknown[] }).residual_risk).length > 0
) {
  records.push(drift("completed run requires empty residual risk"));
}
```

- [ ] **Step 5: Add orchestrator regression.**

In `packages/orchestrator/tests/orchestratorRunV2.test.ts`, add a scenario
that forces completion audit failure after a task run and asserts:

```typescript
expect(state.status).not.toBe("completed");
expect(state.lifecycle_outcome).not.toBe("finished");
expect(state.completion_audit?.status).toBe("failed");
expect(events.some((event) => event.event_type === "platform.invariant_violation")).toBe(true);
```

- [ ] **Step 6: Run targeted verification.**

Run:

```bash
bun test packages/orchestrator/tests/terminalInvariant.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts packages/orchestrator/tests/stateReconciliation.test.ts
```

Expected: PASS.

---

## Task 4: Integrate Recovery Decisions Into The Scheduler

```yaml waygent-task
id: task_4_integrate_recovery_decisions
title: Integrate recovery decisions into the scheduler
dependencies: [task_3_enforce_terminal_completion_invariant]
file_claims:
  - path: packages/orchestrator/src/taskRecovery.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/src/recoveryExecutor.ts
    mode: owned
  - path: packages/orchestrator/tests/recoveryExecutor.test.ts
    mode: owned
  - path: packages/orchestrator/tests/taskRecovery.test.ts
    mode: owned
  - path: packages/orchestrator/tests/orchestratorRunV2.test.ts
    mode: owned
  - path: docs/operations/waygent.md
    mode: owned
risk: high
verify:
  - bun test packages/orchestrator/tests/recoveryExecutor.test.ts packages/orchestrator/tests/taskRecovery.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts
```

**Purpose:** A recoverable task failure should trigger scheduler-owned retry
or decision evidence, not stop as an unstructured blocked run.

- [ ] **Step 1: Add context failure classes to recovery policy.**

In `packages/orchestrator/src/recoveryExecutor.ts`, add entries:

```typescript
  context_missing: { action: "retry_with_evidence", max_attempts: 1 },
  insufficient_context: { action: "retry_with_evidence", max_attempts: 2 },
```

Update the strict prompt suffix so it mentions task packet context:

```typescript
"If the prior failure was context-related, use only the task packet, evidence",
"refs, dependency checkpoint summaries, and spec sections supplied in this retry."
```

- [ ] **Step 2: Add recovery record helper.**

Create `packages/orchestrator/src/taskRecovery.ts`:

```typescript
import type { FailureClass, WaygentRunStateV2 } from "@waygent/contracts";
import { nextRecoveryAction } from "./recoveryExecutor";

export interface SchedulerRecoveryInput {
  state: WaygentRunStateV2;
  task_id: string;
  failure_class: FailureClass | string;
  prior_summary: string;
  evidence_refs: string[];
}

export function priorRecoveryAttempts(state: WaygentRunStateV2, task_id: string, failure_class: FailureClass | string): number {
  return (state.recovery ?? []).filter((record) =>
    record.task_id === task_id && record.failure_class === failure_class
  ).length;
}

export function appendSchedulerRecovery(input: SchedulerRecoveryInput) {
  const prior = priorRecoveryAttempts(input.state, input.task_id, input.failure_class);
  const decision = nextRecoveryAction(input.failure_class, prior, { prior_summary: input.prior_summary });
  const record = {
    task_id: input.task_id,
    failure_class: input.failure_class,
    action: decision.action,
    attempt_number: decision.attempt_number,
    max_attempts: decision.max_attempts,
    automatic: decision.action !== "request_decision" && decision.action !== "halt",
    prior_summary: input.prior_summary,
    result: decision.action === "request_decision" || decision.action === "halt" ? "blocked" : "scheduled",
    evidence_refs: input.evidence_refs
  };
  input.state.recovery.push(record);
  return { decision, record };
}
```

- [ ] **Step 3: Add recovery helper tests.**

Create `packages/orchestrator/tests/taskRecovery.test.ts`:

```typescript
import { describe, expect, test } from "bun:test";
import { appendSchedulerRecovery } from "../src/taskRecovery";
import { runStateFixture } from "./support/runStateFixture";

describe("appendSchedulerRecovery", () => {
  test("schedules strict retry for malformed_result", () => {
    const state = runStateFixture();
    const result = appendSchedulerRecovery({
      state,
      task_id: "task_1",
      failure_class: "malformed_result",
      prior_summary: "provider returned prose",
      evidence_refs: ["worker/task_1.json"]
    });

    expect(result.decision.action).toBe("retry_with_strict_prompt");
    expect(state.recovery[0]).toMatchObject({
      task_id: "task_1",
      failure_class: "malformed_result",
      automatic: true,
      result: "scheduled"
    });
  });

  test("blocks after attempts are exhausted", () => {
    const state = runStateFixture({
      recovery: [
        { task_id: "task_1", failure_class: "malformed_result", action: "retry_with_strict_prompt", attempt_number: 1 },
        { task_id: "task_1", failure_class: "malformed_result", action: "retry_with_strict_prompt", attempt_number: 2 }
      ]
    });

    const result = appendSchedulerRecovery({
      state,
      task_id: "task_1",
      failure_class: "malformed_result",
      prior_summary: "still malformed",
      evidence_refs: []
    });

    expect(result.decision.action).toBe("request_decision");
    expect(result.record.result).toBe("blocked");
  });
});
```

- [ ] **Step 4: Integrate recovery in the wave result loop.**

In `packages/orchestrator/src/orchestrator.ts`, import:

```typescript
import { appendSchedulerRecovery } from "./taskRecovery";
```

When `waveResult.result.status !== "verified"` or a rejected wave result is
encountered, append a scheduler recovery record before marking the task
terminal. Use evidence refs from:

- `waveResult.result.provider_attempt.worker_result_ref`
- `waveResult.result.verification_records[*].kernel_result_ref`
- `waveResult.result.task_packet_path`

If the decision action is retryable, set the graph task status back to
`READY`, set run state task status to `ready`, and let the next safe-wave
projection pick it up. If the decision action is `request_decision` or `halt`,
keep the current blocked behavior.

- [ ] **Step 5: Preserve failure barriers.**

When recovery schedules a retry, emit:

```text
event_type=runway.recovery_scheduled
phase=recover
outcome=success
```

When recovery requests a decision, emit:

```text
event_type=runway.recovery_decision_required
phase=recover
outcome=blocked
```

Both events must include `task_id`, `failure_class`, `action`,
`attempt_number`, `max_attempts`, and `evidence_refs`.

- [ ] **Step 6: Add orchestrator recovery regression.**

In `packages/orchestrator/tests/orchestratorRunV2.test.ts`, add a fake-provider
or process-adapter fixture that fails first with `malformed_result` and then
returns a valid worker result. Assert:

```typescript
expect(state.recovery.some((record) =>
  record.task_id === "task_retry" &&
  record.failure_class === "malformed_result" &&
  record.action === "retry_with_strict_prompt"
)).toBe(true);
expect(events.some((event) => event.event_type === "runway.recovery_scheduled")).toBe(true);
expect(state.status).toBe("completed");
expect(state.completion_audit?.status).toBe("passed");
```

- [ ] **Step 7: Document the scheduler recovery loop.**

In `docs/operations/waygent.md`, add:

```markdown
### Scheduler Recovery Loop

Recoverable task failures are routed through `nextRecoveryAction` before the
run is blocked. Waygent records each attempt in `state.recovery[]`, emits either
`runway.recovery_scheduled` or `runway.recovery_decision_required`, and retries
only from safe task boundaries. Recovery never changes completion audit
requirements.
```

- [ ] **Step 8: Run targeted verification.**

Run:

```bash
bun test packages/orchestrator/tests/recoveryExecutor.test.ts packages/orchestrator/tests/taskRecovery.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts
```

Expected: PASS.

---

## Task 5: Require Review Evidence When Review Mode Requires It

```yaml waygent-task
id: task_5_require_review_evidence
title: Require review evidence when review mode requires it
dependencies: [task_4_integrate_recovery_decisions]
file_claims:
  - path: packages/orchestrator/src/reviewEvidence.ts
    mode: owned
  - path: packages/orchestrator/src/reviewGate.ts
    mode: owned
  - path: packages/orchestrator/src/completionAudit.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/tests/reviewEvidence.test.ts
    mode: owned
  - path: packages/orchestrator/tests/reviewGate.test.ts
    mode: owned
  - path: packages/orchestrator/tests/orchestratorRunV2.test.ts
    mode: owned
  - path: docs/operations/waygent.md
    mode: owned
risk: high
verify:
  - bun test packages/orchestrator/tests/reviewEvidence.test.ts packages/orchestrator/tests/reviewGate.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts
```

**Purpose:** If the selected run mode requires review, empty
`completion_audit.review_evidence` blocks apply readiness.

- [ ] **Step 1: Add review evidence helper.**

Create `packages/orchestrator/src/reviewEvidence.ts`:

```typescript
import type { WaygentRunStateV2 } from "@waygent/contracts";

export interface ReviewEvidencePolicy {
  required: boolean;
  reason: string | null;
}

export function reviewEvidencePolicy(state: WaygentRunStateV2): ReviewEvidencePolicy {
  if (state.method_evidence_required) {
    return { required: true, reason: "method_evidence_required" };
  }
  if (Object.values(state.tasks).some((task) => task.risk === "high")) {
    return { required: true, reason: "high_risk_task" };
  }
  if ((state.recovery ?? []).length > 0) {
    return { required: true, reason: "recovery_attempted" };
  }
  return { required: false, reason: null };
}

export function reviewEvidenceMissing(input: {
  state: WaygentRunStateV2;
  review_evidence: Array<Record<string, unknown>>;
}): string | null {
  const policy = reviewEvidencePolicy(input.state);
  if (!policy.required) return null;
  return input.review_evidence.length > 0 ? null : policy.reason ?? "review_required";
}
```

- [ ] **Step 2: Add review evidence tests.**

Create `packages/orchestrator/tests/reviewEvidence.test.ts`:

```typescript
import { describe, expect, test } from "bun:test";
import { reviewEvidenceMissing, reviewEvidencePolicy } from "../src/reviewEvidence";
import { runStateFixture } from "./support/runStateFixture";

describe("review evidence policy", () => {
  test("requires review for high-risk tasks", () => {
    const state = runStateFixture({
      tasks: {
        task_1: {
          id: "task_1",
          status: "verified",
          risk: "high",
          dependencies: [],
          file_claims: [],
          attempts: [],
          task_packet_path: null,
          task_packet_sha256: null,
          unit_manifest: {},
          checkpoint_refs: ["checkpoint/task_1.json"],
          latest_failure_class: null,
          decision_packet_ref: null,
          timing: {}
        }
      }
    });

    expect(reviewEvidencePolicy(state)).toMatchObject({ required: true, reason: "high_risk_task" });
    expect(reviewEvidenceMissing({ state, review_evidence: [] })).toBe("high_risk_task");
  });

  test("accepts present review evidence", () => {
    const state = runStateFixture({ method_evidence_required: true });
    expect(reviewEvidenceMissing({ state, review_evidence: [{ verdict: "pass" }] })).toBeNull();
  });
});
```

- [ ] **Step 3: Wire review evidence into completion audit.**

In `packages/orchestrator/src/completionAudit.ts`, import
`reviewEvidenceMissing` and add review residual risk:

```typescript
const missingReviewReason = reviewEvidenceMissing({
  state: input.state,
  review_evidence: input.review_evidence
});
if (missingReviewReason) {
  residualRisk.push(`review_evidence:${missingReviewReason}`);
}
```

Update audit status:

```typescript
status: failed.length === 0 && taskResults.length > 0 && combinedApplyOk && !missingReviewReason ? "passed" : "failed",
```

- [ ] **Step 4: Build compact review packets during orchestration.**

In `packages/orchestrator/src/orchestrator.ts`, after task verification and
before `buildCompletionAudit`, collect review evidence from `state.reviews`.
For the first implementation, do not spawn a live reviewer. Instead, require
pre-existing review evidence in `state.reviews` when policy says review is
required. This keeps the completion gate honest and leaves active reviewer
dispatch for the follow-up plan.

Use:

```typescript
const reviewEvidence = state.reviews.map((review) => ({
  task_id: review.task_id,
  attempt_id: review.attempt_id,
  verdict: review.verdict,
  spec_score: review.spec_score,
  quality_score: review.quality_score,
  residual_risk: review.residual_risk
}));
```

Pass `reviewEvidence` into `buildCompletionAudit`.

- [ ] **Step 5: Add completion audit regression.**

In `packages/orchestrator/tests/orchestratorRunV2.test.ts`, add a high-risk
task scenario with no review evidence. Assert:

```typescript
expect(state.status).toBe("blocked");
expect(state.completion_audit?.status).toBe("failed");
expect(state.completion_audit?.residual_risk).toContain("review_evidence:high_risk_task");
```

Then add a second scenario with one passing review result in `state.reviews`
before audit and assert:

```typescript
expect(state.completion_audit?.review_evidence).toHaveLength(1);
expect(state.completion_audit?.residual_risk ?? []).not.toContain("review_evidence:high_risk_task");
```

- [ ] **Step 6: Document review evidence gate.**

In `docs/operations/waygent.md`, add:

```markdown
### Review Evidence Gate

When a task is high risk, a recovery attempt occurred, or method evidence is
required, completion audit requires review evidence. Missing review evidence is
recorded as `review_evidence:<reason>` in residual risk and blocks completed
status.
```

- [ ] **Step 7: Run targeted verification.**

Run:

```bash
bun test packages/orchestrator/tests/reviewEvidence.test.ts packages/orchestrator/tests/reviewGate.test.ts packages/orchestrator/tests/orchestratorRunV2.test.ts
```

Expected: PASS.

---

## Task 6: Full Runtime Verification And Documentation Pass

```yaml waygent-task
id: task_6_full_runtime_verification
title: Full runtime verification and documentation pass
dependencies:
  - task_5_require_review_evidence
file_claims:
  - path: docs/operations/waygent.md
    mode: owned
  - path: docs/operations/plan-authoring.md
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
  - git diff --check
```

**Purpose:** Prove the quality loop works as a coherent runtime change and
refresh repository map evidence after the code/documentation structure changes.

- [ ] **Step 1: Update docs for the complete flow.**

Ensure `docs/operations/waygent.md` describes this order:

```text
intake recovery -> plan preflight -> context packet gate -> provider dispatch
-> verification -> checkpoint -> scheduler recovery -> review evidence gate
-> completion audit -> reconciliation -> terminal invariant guard
```

Ensure `docs/operations/plan-authoring.md` states that `verify` must contain
only non-mutating checks and that implementation-only commands are preserved as
task instructions during normalization.

- [ ] **Step 2: Refresh Graphify output after implementation.**

Run this outside the `verify` list because it mutates generated files:

```bash
graphify update .
```

Expected: `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.json` update
successfully.

- [ ] **Step 3: Run full verification.**

Run:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: Inspect final status.**

Run:

```bash
git status --short --branch --untracked-files=all
```

Expected: only intentional code, docs, tests, and Graphify output files are
dirty.

---

## Self-Review Checklist

- **Spec coverage:** Stage -1 maps to Task 1. Stage 0 maps to Task 2. Stage A
  maps to Task 3. Stage B maps to Task 4. Stage C maps to Task 5. Full
  verification and docs map to Task 6.
- **Waygent executability:** Every task has a fenced `yaml waygent-task` block
  with `id`, `title`, `dependencies`, `file_claims`, `risk`, and safe `verify`
  commands.
- **Context reduction:** Task 2 blocks red packets before provider dispatch,
  so the main coordinator no longer needs to inline oversize worker context.
- **Quality guard:** Tasks 3 and 5 make false completion impossible when audit
  or review evidence is missing.
- **Recovery guard:** Task 4 integrates `nextRecoveryAction` into scheduler
  state instead of leaving it as a passive helper.
