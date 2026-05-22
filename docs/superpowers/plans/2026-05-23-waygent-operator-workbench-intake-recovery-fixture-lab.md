# Waygent Operator Workbench Intake Recovery Fixture-Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Waygent intake recovery so recoverable plan/spec shape issues no longer stop execution, and expose the resulting judgment through the operator Workbench, API, CLI, and Fixture-Lab regression tests.

**Architecture:** Add an additive intake recovery contract to `waygent.run_state.v2`, implement a deterministic-first intake repair module before plan preflight, persist normalized plan and recovery report artifacts, and project intake state through the existing `waygent.operator_decision.v1` read model. Fixture-Lab then verifies recoverable and unsafe inputs from raw documents/provider artifacts through operator decisions.

**Tech Stack:** Bun, TypeScript, Waygent monorepo packages, `@waygent/contracts`, `@waygent/orchestrator`, `@waygent/lens-projectors`, local filesystem JSON/JSONL artifacts, Bun test.

---

## Context

- Design spec: `docs/superpowers/specs/2026-05-23-waygent-operator-workbench-intake-recovery-fixture-lab-design.md`
- Current plan parsing: `packages/orchestrator/src/planParser.ts`
- Current superpowers normalization: `packages/orchestrator/src/planNormalizer.ts`
- Current preflight: `packages/orchestrator/src/planPreflight.ts`
- Current run lifecycle: `packages/orchestrator/src/orchestrator.ts`
- Current operator projection: `packages/lens-projectors/src/operatorDecision.ts`
- Current API detail surface: `apps/api/src/server.ts`
- Current console model: `apps/console/src/uiModel.ts`

## File Structure

- `packages/contracts/src/types.ts`: add intake recovery contracts and optional state/projection fields.
- `packages/contracts/src/schemas.ts`: validate intake recovery state and optional operator projection summary.
- `packages/orchestrator/src/intakeRecovery.ts`: own strict normalization fallback, deterministic repair, high-risk classification, report rendering, and blocked-run helpers.
- `packages/orchestrator/src/orchestrator.ts`: call intake recovery before plan preflight, write intake artifacts, emit intake events, and create blocked run state when user input is required.
- `packages/orchestrator/src/index.ts`: export intake recovery helpers for focused tests.
- `packages/lens-projectors/src/operatorDecision.ts`: add intake blockers, evidence refs, and next actions from run state intake recovery.
- `apps/api/src/server.ts`: return the same operator projection with intake recovery data; avoid API-local judgment.
- `apps/console/src/uiModel.ts`: expose intake recovery in the Workbench detail model.
- `tests/fixtures/waygent-lab/`: hold bad-but-recoverable and unsafe raw plan/spec/provider fixtures.
- `tests/integration/waygent-fixture-lab.test.ts`: run lab cases through the public runtime/projection path.
- `docs/operations/waygent.md`, `docs/contracts/run-state.md`, `skills/waygent/SKILL.md`: document the new operator behavior and stop rules.

## Execution Order

- Sequential/shared-core tasks: Task 1, Task 2, Task 3, Task 4, Task 5, Task 6.
- Parallel-safe after Task 3 lands: Task 4 API/Console presentation and Task 5 additional fixture cases can be split between agents, but both must merge against the Task 3 contracts.
- Human approval gates: none during implementation unless a new destructive-command policy or provider-auth policy is added beyond this plan.

---

### Task 1: Intake Recovery Contracts

```yaml waygent-task
id: task_1_intake_recovery_contracts
title: Intake Recovery Contracts
dependencies: []
file_claims:
  - path: packages/contracts/src/types.ts
    mode: owned
  - path: packages/contracts/src/schemas.ts
    mode: owned
  - path: packages/contracts/tests/contracts.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/contracts/tests/contracts.test.ts
  - git diff --check -- packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/contracts/tests/contracts.test.ts
```

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Test: `packages/contracts/tests/contracts.test.ts`

- [ ] **Step 1: Add the failing contract test**

Add this test inside `describe("Waygent contracts", () => { ... })` in `packages/contracts/tests/contracts.test.ts` after the existing Waygent v2 state test:

```ts
  test("accepts intake recovery state and operator projection summary", () => {
    const intake = {
      status: "recovered",
      started_at: "2026-05-23T00:00:00.000Z",
      completed_at: "2026-05-23T00:00:01.000Z",
      normalized_plan_ref: "artifacts/intake/normalized-plan.md",
      recovery_report_ref: "artifacts/intake/recovery-report.json",
      findings: [
        {
          code: "task_body_not_yaml",
          severity: "warning",
          message: "Task 1 used prose instead of waygent-task YAML.",
          task_id: "task_1_update_readme",
          evidence_refs: ["plan:plan.md#task-1"]
        }
      ],
      repair_actions: [
        {
          action: "deterministic_superpowers_normalization",
          status: "applied",
          reason: "Recovered file claims and verification commands from markdown sections.",
          evidence_refs: ["artifacts/intake/normalized-plan.md"]
        }
      ],
      can_start: true,
      confidence: "deterministic",
      question: null
    };

    const state: WaygentRunStateV2 = {
      schema: "waygent.run_state.v2",
      run_id: "run_intake",
      workspace: "/tmp/workspace",
      source_branch: "main",
      worktree_root: "/tmp/worktrees",
      run_root: "/tmp/run",
      artifact_root: "/tmp/run/artifacts",
      state_path: "/tmp/run/state.json",
      event_journal_path: "/tmp/run/events.jsonl",
      plan_path: "/tmp/workspace/plan.md",
      spec_path: "/tmp/workspace/spec.md",
      provider_profile: { provider: "fake" },
      intake_recovery: intake,
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
        started_at: "2026-05-23T00:00:00.000Z",
        updated_at: "2026-05-23T00:00:01.000Z",
        completed_at: "2026-05-23T00:00:01.000Z"
      }
    };

    expect(validateContract("waygent.run_state.v2", state)).toEqual(state);

    const decision = validateContract("waygent.operator_decision.v1", {
      schema: "waygent.operator_decision.v1",
      run_id: "run_intake",
      generated_at: "2026-05-23T00:00:02.000Z",
      status_summary: {
        display_status: "done",
        runtime_status: "completed",
        lifecycle_outcome: "finished",
        current_phase: "complete",
        active_tasks: 0,
        completed_tasks: 0,
        blocked_tasks: 0,
        apply_status: "not_ready",
        summary: "run_intake completed after deterministic intake recovery."
      },
      primary_blocker: null,
      secondary_blockers: [],
      allowed_actions: [],
      blocked_actions: [],
      evidence_packet: {
        state_refs: ["state:/tmp/run/state.json"],
        event_refs: [],
        artifact_refs: ["artifacts/intake/normalized-plan.md", "artifacts/intake/recovery-report.json"],
        verification_refs: [],
        checkpoint_refs: [],
        projection_refs: [],
        missing_refs: [],
        redaction_notes: []
      },
      ai_handoff: {
        purpose: "summarize_blocker",
        prompt_summary: "Summarize the intake recovery result.",
        run_id: "run_intake",
        current_status: "done",
        primary_blocker: null,
        secondary_blockers: [],
        allowed_action_ids: [],
        blocked_action_ids: [],
        constraints: ["Do not override Waygent runtime policy."],
        evidence_refs: ["artifacts/intake/recovery-report.json"],
        missing_evidence: [],
        raw_fallback_refs: [],
        safety_notes: ["Waygent runtime remains apply authority."]
      },
      confidence: "deterministic",
      unknown_reasons: [],
      intake_recovery: {
        status: "recovered",
        can_start: true,
        confidence: "deterministic",
        finding_codes: ["task_body_not_yaml"],
        artifact_refs: ["artifacts/intake/normalized-plan.md", "artifacts/intake/recovery-report.json"],
        question: null
      },
      source_projection_refs: {
        run_state_v2: "state:/tmp/run/state.json",
        apply_readiness: "waygent.apply_readiness",
        execution_explanation: "waygent.execution_explanation.v1",
        operational_maturity: "waygent.operational_maturity.v1"
      }
    });

    expect(decision.intake_recovery).toMatchObject({ status: "recovered", can_start: true });
  });
```

- [ ] **Step 2: Run the focused contract test and confirm it fails**

Run: `bun test packages/contracts/tests/contracts.test.ts`

Expected: FAIL with TypeScript or contract validation errors referencing `intake_recovery` or `additionalProperties`.

- [ ] **Step 3: Add TypeScript contract types**

Add these exports near the existing runtime improvement types in `packages/contracts/src/types.ts`:

```ts
export type IntakeRecoveryStatus = "not_needed" | "recovered" | "decision_required" | "failed";
export type IntakeRecoveryConfidence = "deterministic" | "ai_assisted" | "blocked";
export type IntakeFindingSeverity = "info" | "warning" | "blocking";

export type IntakeFindingCode =
  | "task_heading_unrecognized"
  | "task_body_not_yaml"
  | "missing_frontmatter"
  | "single_spec_candidate_by_basename"
  | "file_claims_in_prose"
  | "verification_command_in_prose"
  | "verification_command_unclassified_but_safe"
  | "plan_section_body_sparse_but_spec_section_available"
  | "multiple_plan_or_spec_candidates"
  | "destructive_command_candidate"
  | "conflicting_owned_claim"
  | "path_escape"
  | "missing_verification_for_source_mutation"
  | "external_credentials_required"
  | "scope_expansion"
  | "apply_without_verification_evidence";

export interface IntakeFinding {
  code: IntakeFindingCode | string;
  severity: IntakeFindingSeverity;
  message: string;
  task_id: string | null;
  evidence_refs: string[];
}

export interface IntakeRepairAction {
  action: string;
  status: "applied" | "blocked" | "skipped";
  reason: string;
  evidence_refs: string[];
}

export interface WaygentIntakeRecovery {
  status: IntakeRecoveryStatus;
  started_at: string;
  completed_at: string;
  normalized_plan_ref: string | null;
  recovery_report_ref: string | null;
  findings: IntakeFinding[];
  repair_actions: IntakeRepairAction[];
  can_start: boolean;
  confidence: IntakeRecoveryConfidence;
  question: string | null;
}

export interface OperatorIntakeRecoverySummary {
  status: IntakeRecoveryStatus;
  can_start: boolean;
  confidence: IntakeRecoveryConfidence;
  finding_codes: string[];
  artifact_refs: string[];
  question: string | null;
}
```

Add optional fields:

```ts
export interface OperatorDecisionProjection {
  schema: "waygent.operator_decision.v1";
  run_id: string;
  generated_at: string;
  status_summary: OperatorStatusSummary;
  primary_blocker: OperatorBlocker | null;
  secondary_blockers: OperatorBlocker[];
  allowed_actions: OperatorAllowedAction[];
  blocked_actions: OperatorBlockedAction[];
  evidence_packet: OperatorEvidencePacket;
  ai_handoff: OperatorAiHandoff;
  confidence: OperatorDecisionConfidence;
  unknown_reasons: string[];
  intake_recovery?: OperatorIntakeRecoverySummary;
  source_projection_refs: OperatorSourceProjectionRefs;
}
```

Add `intake_recovery?: WaygentIntakeRecovery;` to `WaygentRunStateV2` after `provider_profile`.

- [ ] **Step 4: Add JSON schemas**

In `packages/contracts/src/schemas.ts`, add these schema constants near `specManifestSchema`:

```ts
const intakeFindingSchema = {
  type: "object",
  additionalProperties: false,
  required: ["code", "severity", "message", "task_id", "evidence_refs"],
  properties: {
    code: { type: "string", minLength: 1 },
    severity: { enum: ["info", "warning", "blocking"] },
    message: { type: "string", minLength: 1 },
    task_id: { type: "string", nullable: true },
    evidence_refs: { type: "array", items: { type: "string", minLength: 1 } }
  }
} as const;

const intakeRepairActionSchema = {
  type: "object",
  additionalProperties: false,
  required: ["action", "status", "reason", "evidence_refs"],
  properties: {
    action: { type: "string", minLength: 1 },
    status: { enum: ["applied", "blocked", "skipped"] },
    reason: { type: "string", minLength: 1 },
    evidence_refs: { type: "array", items: { type: "string", minLength: 1 } }
  }
} as const;

const intakeRecoverySchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "status",
    "started_at",
    "completed_at",
    "normalized_plan_ref",
    "recovery_report_ref",
    "findings",
    "repair_actions",
    "can_start",
    "confidence",
    "question"
  ],
  properties: {
    status: { enum: ["not_needed", "recovered", "decision_required", "failed"] },
    started_at: { type: "string", pattern: isoTimestamp },
    completed_at: { type: "string", pattern: isoTimestamp },
    normalized_plan_ref: { type: "string", nullable: true },
    recovery_report_ref: { type: "string", nullable: true },
    findings: { type: "array", items: intakeFindingSchema },
    repair_actions: { type: "array", items: intakeRepairActionSchema },
    can_start: { type: "boolean" },
    confidence: { enum: ["deterministic", "ai_assisted", "blocked"] },
    question: { type: "string", nullable: true }
  }
} as const;
```

Add `intake_recovery: intakeRecoverySchema,` to `waygentRunStateV2Schema.properties`.

Add this optional schema property to `operatorDecisionProjectionSchema.properties`:

```ts
    intake_recovery: {
      type: "object",
      additionalProperties: false,
      nullable: true,
      required: ["status", "can_start", "confidence", "finding_codes", "artifact_refs", "question"],
      properties: {
        status: { enum: ["not_needed", "recovered", "decision_required", "failed"] },
        can_start: { type: "boolean" },
        confidence: { enum: ["deterministic", "ai_assisted", "blocked"] },
        finding_codes: { type: "array", items: { type: "string", minLength: 1 } },
        artifact_refs: { type: "array", items: { type: "string", minLength: 1 } },
        question: { type: "string", nullable: true }
      }
    },
```

Do not add `intake_recovery` to the required list for operator decisions; existing projections without intake data must remain valid.

- [ ] **Step 5: Run the focused test and commit**

Run: `bun test packages/contracts/tests/contracts.test.ts`

Expected: PASS.

Then run: `git diff --check -- packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/contracts/tests/contracts.test.ts`

Expected: no output.

Commit:

```bash
git add packages/contracts/src/types.ts packages/contracts/src/schemas.ts packages/contracts/tests/contracts.test.ts
git commit -m "feat: add Waygent intake recovery contracts"
```

---

### Task 2: Deterministic Intake Recovery Module

```yaml waygent-task
id: task_2_deterministic_intake_recovery
title: Deterministic Intake Recovery Module
dependencies: [task_1_intake_recovery_contracts]
file_claims:
  - path: packages/orchestrator/src/intakeRecovery.ts
    mode: owned
  - path: packages/orchestrator/src/index.ts
    mode: owned
  - path: packages/orchestrator/tests/intakeRecovery.test.ts
    mode: owned
  - path: packages/orchestrator/tests/fixtures/intake_recovery_bad_plan.md
    mode: owned
  - path: packages/orchestrator/tests/fixtures/intake_recovery_unsafe_plan.md
    mode: owned
risk: high
verify:
  - bun test packages/orchestrator/tests/intakeRecovery.test.ts
  - git diff --check -- packages/orchestrator/src/intakeRecovery.ts packages/orchestrator/src/index.ts packages/orchestrator/tests/intakeRecovery.test.ts packages/orchestrator/tests/fixtures/intake_recovery_bad_plan.md packages/orchestrator/tests/fixtures/intake_recovery_unsafe_plan.md
```

**Files:**
- Create: `packages/orchestrator/src/intakeRecovery.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Create: `packages/orchestrator/tests/intakeRecovery.test.ts`
- Create: `packages/orchestrator/tests/fixtures/intake_recovery_bad_plan.md`
- Create: `packages/orchestrator/tests/fixtures/intake_recovery_unsafe_plan.md`

- [ ] **Step 1: Add fixture markdown files**

Create `packages/orchestrator/tests/fixtures/intake_recovery_bad_plan.md`:

````md
# Bad But Recoverable Plan

### Task 1: Update README

Change `README.md` so the operator docs mention intake recovery.

Verification:

```bash
git diff --check -- README.md
```
````

Create `packages/orchestrator/tests/fixtures/intake_recovery_unsafe_plan.md`:

````md
# Unsafe Intake Plan

### Task 1: Reset workspace

Modify `README.md` and then run this cleanup.

```bash
rm -rf .
```
````

- [ ] **Step 2: Add failing intake recovery tests**

Create `packages/orchestrator/tests/intakeRecovery.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parseWaygentPlan } from "../src/planParser";
import { recoverWaygentPlanInput } from "../src/intakeRecovery";

function fixture(name: string): string {
  return readFileSync(join(import.meta.dir, "fixtures", name), "utf8");
}

describe("Waygent intake recovery", () => {
  test("recovers prose tasks with traceable file claims and verification", () => {
    const recovered = recoverWaygentPlanInput({
      markdown: fixture("intake_recovery_bad_plan.md"),
      path: "/tmp/intake_recovery_bad_plan.md",
      workspace: "/tmp/workspace",
      spec_markdown: "# Intake Recovery Design\n\n## README\nMention intake recovery.\n",
      spec_path: "/tmp/spec.md"
    });

    expect(recovered.status).toBe("recovered");
    expect(recovered.normalized_plan.task_count).toBe(1);
    expect(recovered.report.can_start).toBe(true);
    expect(recovered.report.findings.map((finding) => finding.code)).toContain("task_body_not_yaml");
    expect(recovered.report.findings.map((finding) => finding.code)).toContain("file_claims_in_prose");
    expect(recovered.report.findings.map((finding) => finding.code)).toContain("verification_command_in_prose");

    const parsed = parseWaygentPlan(recovered.normalized_plan.markdown);
    expect(parsed.tasks[0]).toMatchObject({
      id: "task_1_update_readme",
      title: "Update README",
      file_claims: [{ path: "README.md", mode: "owned" }],
      verification_commands: ["git diff --check -- README.md"]
    });
  });

  test("blocks destructive command candidates instead of repairing them", () => {
    const recovered = recoverWaygentPlanInput({
      markdown: fixture("intake_recovery_unsafe_plan.md"),
      path: "/tmp/intake_recovery_unsafe_plan.md",
      workspace: "/tmp/workspace",
      spec_markdown: "",
      spec_path: null
    });

    expect(recovered.status).toBe("decision_required");
    expect(recovered.report.can_start).toBe(false);
    expect(recovered.report.question).toContain("destructive command");
    expect(recovered.report.findings).toContainEqual(expect.objectContaining({
      code: "destructive_command_candidate",
      severity: "blocking"
    }));
  });
});
```

- [ ] **Step 3: Run the focused test and confirm it fails**

Run: `bun test packages/orchestrator/tests/intakeRecovery.test.ts`

Expected: FAIL because `../src/intakeRecovery` does not exist.

- [ ] **Step 4: Create the intake recovery module**

Create `packages/orchestrator/src/intakeRecovery.ts` with this implementation:

```ts
import type {
  IntakeFinding,
  IntakeRepairAction,
  WaygentIntakeRecovery
} from "@waygent/contracts";
import type { FileClaim, FileClaimMode } from "@waygent/runway-control";
import {
  normalizeWaygentPlanInput,
  type NormalizedWaygentPlan
} from "./planNormalizer";
import { scaffoldWaygentTask } from "./planScaffold";

export interface RecoverWaygentPlanInput {
  markdown: string;
  path: string | null;
  workspace: string;
  spec_markdown: string;
  spec_path: string | null;
  unsafe_verification?: boolean;
  infer_risk?: boolean;
}

export interface RecoveredWaygentPlan {
  status: WaygentIntakeRecovery["status"];
  normalized_plan: NormalizedWaygentPlan;
  report: WaygentIntakeRecovery;
}

interface LenientTaskSection {
  number: number;
  title: string;
  body: string;
}

const TASK_HEADING = /^#{1,4}\s+(?:Task|작업|Phase)\s+(\d+)\s*[:.)-]?\s*(.*)$/gim;
const INLINE_PATH = /`([^`]+\.(?:ts|tsx|js|jsx|json|md|mdx|toml|yaml|yml|rs|py|sh|css|html))`/g;
const FENCED_COMMAND = /```(?:bash|sh|shell)?\r?\n([\s\S]*?)\r?\n```/gim;
const DESTRUCTIVE_COMMAND = /\b(rm\s+-rf|git\s+reset\s+--hard|git\s+clean\s+-fd|drop\s+table|kubectl\s+delete)\b/i;
const SAFE_VERIFY_PREFIXES = [
  "bun test",
  "bun run check",
  "bun run typecheck",
  "bun run build",
  "bun run waygent:scenarios",
  "bun run waygent:dogfood",
  "cargo test",
  "npm test",
  "npm run test",
  "pnpm test",
  "yarn test",
  "test ",
  "git diff --check",
  "printf "
];

export function recoverWaygentPlanInput(input: RecoverWaygentPlanInput): RecoveredWaygentPlan {
  const startedAt = new Date().toISOString();
  try {
    const normalized = normalizeWaygentPlanInput({
      markdown: input.markdown,
      path: input.path,
      workspace: input.workspace,
      unsafe_verification: input.unsafe_verification,
      infer_risk: input.infer_risk
    });
    return {
      status: "not_needed",
      normalized_plan: normalized,
      report: {
        status: "not_needed",
        started_at: startedAt,
        completed_at: new Date().toISOString(),
        normalized_plan_ref: null,
        recovery_report_ref: null,
        findings: [],
        repair_actions: [],
        can_start: true,
        confidence: "deterministic",
        question: null
      }
    };
  } catch (error) {
    return deterministicRepair(input, startedAt, error instanceof Error ? error.message : String(error));
  }
}

function deterministicRepair(
  input: RecoverWaygentPlanInput,
  startedAt: string,
  strictError: string
): RecoveredWaygentPlan {
  const findings: IntakeFinding[] = [{
    code: "task_body_not_yaml",
    severity: "warning",
    message: strictError,
    task_id: null,
    evidence_refs: planEvidence(input.path)
  }];
  const actions: IntakeRepairAction[] = [];
  const sections = extractLenientTaskSections(input.markdown);
  const tasks = sections.map((section) => recoverSection(section, findings, input.path));
  for (let index = 1; index < tasks.length; index += 1) {
    tasks[index]!.dependencies = [tasks[index - 1]!.id];
  }
  const blocking = findings.filter((finding) => finding.severity === "blocking");
  const canStart = tasks.length > 0 && blocking.length === 0;
  const status: WaygentIntakeRecovery["status"] = canStart ? "recovered" : "decision_required";
  const normalizedMarkdown = canStart
    ? [
      "# Normalized Waygent Plan",
      "",
      `Source: ${input.path || "inline"}`,
      "",
      ...tasks.map((task) => scaffoldWaygentTask(task))
    ].join("\n")
    : input.markdown;

  if (canStart) {
    actions.push({
      action: "deterministic_markdown_intake_repair",
      status: "applied",
      reason: "Recovered executable task blocks from markdown headings, path references, and safe verification commands.",
      evidence_refs: ["artifacts/intake/normalized-plan.md"]
    });
  } else {
    actions.push({
      action: "deterministic_markdown_intake_repair",
      status: "blocked",
      reason: "High-risk ambiguity prevents automatic execution.",
      evidence_refs: planEvidence(input.path)
    });
  }

  const report: WaygentIntakeRecovery = {
    status,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    normalized_plan_ref: canStart ? "artifacts/intake/normalized-plan.md" : null,
    recovery_report_ref: "artifacts/intake/recovery-report.json",
    findings,
    repair_actions: actions,
    can_start: canStart,
    confidence: canStart ? "deterministic" : "blocked",
    question: canStart ? null : questionFor(blocking)
  };

  return {
    status,
    normalized_plan: {
      markdown: normalizedMarkdown,
      path: input.path,
      mode: canStart ? "superpowers" : "native",
      task_count: canStart ? tasks.length : 0,
      diagnostics: findings.map((finding) => `${finding.code}: ${finding.message}`)
    },
    report
  };
}

function recoverSection(section: LenientTaskSection, findings: IntakeFinding[], planPath: string | null) {
  const taskId = `task_${section.number}_${slugify(section.title)}`;
  const evidenceRefs = [...planEvidence(planPath), `plan:task-${section.number}`];
  const fileClaims = extractFileClaims(section.body, findings, taskId, evidenceRefs);
  const verify = extractVerificationCommands(section.body, findings, taskId, evidenceRefs);
  if (DESTRUCTIVE_COMMAND.test(section.body)) {
    findings.push({
      code: "destructive_command_candidate",
      severity: "blocking",
      message: `Task ${section.number} contains a destructive command candidate.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  if (fileClaims.length === 0) {
    findings.push({
      code: "file_claims_in_prose",
      severity: "blocking",
      message: `Task ${section.number} has no recoverable file claim.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  if (verify.length === 0) {
    findings.push({
      code: "missing_verification_for_source_mutation",
      severity: "blocking",
      message: `Task ${section.number} has no safe verification command.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  return {
    id: taskId,
    title: section.title,
    dependencies: [],
    file_claims: fileClaims,
    // Recovered tasks are always high risk regardless of finding severity.
    // The strict YAML waygent-task block is the only contract a task author
    // can use to declare a lower risk; recovered tasks have not been authored
    // under that contract. See design "Recovered Task Risk Classification".
    risk: "high" as const,
    verify,
    instructions: instructionLines(section.body)
  };
}

function extractLenientTaskSections(markdown: string): LenientTaskSection[] {
  const headings = [...markdown.matchAll(TASK_HEADING)];
  return headings.map((match, index) => {
    const start = typeof match.index === "number" ? match.index : 0;
    const nextIndex = index + 1 < headings.length ? headings[index + 1]!.index : undefined;
    const end = typeof nextIndex === "number" ? nextIndex : markdown.length;
    const rawTitle = (match[2] || "").trim();
    return {
      number: Number(match[1]),
      title: rawTitle || `Task ${match[1]}`,
      body: markdown.slice(start, end)
    };
  });
}

function extractFileClaims(body: string, findings: IntakeFinding[], taskId: string, evidenceRefs: string[]): FileClaim[] {
  const claims: FileClaim[] = [];
  for (const match of body.matchAll(INLINE_PATH)) {
    const path = (match[1] || "").trim();
    if (!path || path.includes("..")) continue;
    claims.push({ path, mode: inferClaimMode(body, path) });
  }
  const unique = new Map(claims.map((claim) => [claim.path, claim]));
  if (unique.size > 0) {
    findings.push({
      code: "file_claims_in_prose",
      severity: "warning",
      message: `Recovered ${unique.size} file claim(s) from prose.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  return [...unique.values()];
}

function inferClaimMode(body: string, path: string): FileClaimMode {
  const before = body.slice(Math.max(0, body.indexOf(path) - 80), body.indexOf(path)).toLowerCase();
  if (/\b(read|inspect|review)\b/.test(before)) return "read_only";
  if (/\b(append|add to)\b/.test(before)) return "shared_append";
  return "owned";
}

function extractVerificationCommands(body: string, findings: IntakeFinding[], taskId: string, evidenceRefs: string[]): string[] {
  const commands = [...body.matchAll(FENCED_COMMAND)]
    .flatMap((match) => logicalCommandLines(match[1] || ""))
    .filter((command) => SAFE_VERIFY_PREFIXES.some((prefix) => command === prefix.trim() || command.startsWith(prefix)));
  const unique = [...new Set(commands)];
  if (unique.length > 0) {
    findings.push({
      code: "verification_command_in_prose",
      severity: "warning",
      message: `Recovered ${unique.length} verification command(s) from prose.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  return unique;
}

function logicalCommandLines(raw: string): string[] {
  return raw.split(/\r?\n/).map((line) => line.trim()).filter((line) => line && !line.startsWith("#"));
}

function instructionLines(body: string): string[] {
  return body.split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("```") && !line.startsWith("#"))
    .slice(0, 20);
}

function questionFor(blocking: IntakeFinding[]): string {
  if (blocking.some((finding) => finding.code === "destructive_command_candidate")) {
    return "The plan contains a destructive command candidate. Confirm the intended safe replacement before execution.";
  }
  return "Waygent could not recover a safe executable plan. Provide explicit file claims and verification commands.";
}

function planEvidence(path: string | null): string[] {
  return [path ? `plan:${path}` : "plan:inline"];
}

function slugify(title: string): string {
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return slug || "task";
}
```

- [ ] **Step 5: Export the module**

Add this line to `packages/orchestrator/src/index.ts`:

```ts
export * from "./intakeRecovery";
```

- [ ] **Step 6: Run tests and commit**

Run: `bun test packages/orchestrator/tests/intakeRecovery.test.ts`

Expected: PASS.

Run: `git diff --check -- packages/orchestrator/src/intakeRecovery.ts packages/orchestrator/src/index.ts packages/orchestrator/tests/intakeRecovery.test.ts packages/orchestrator/tests/fixtures/intake_recovery_bad_plan.md packages/orchestrator/tests/fixtures/intake_recovery_unsafe_plan.md`

Expected: no output.

Commit:

```bash
git add packages/orchestrator/src/intakeRecovery.ts packages/orchestrator/src/index.ts packages/orchestrator/tests/intakeRecovery.test.ts packages/orchestrator/tests/fixtures/intake_recovery_bad_plan.md packages/orchestrator/tests/fixtures/intake_recovery_unsafe_plan.md
git commit -m "feat: add deterministic intake recovery"
```

---

### Task 3: Run Lifecycle Integration

```yaml waygent-task
id: task_3_run_lifecycle_integration
title: Run Lifecycle Integration
dependencies: [task_2_deterministic_intake_recovery]
file_claims:
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/orchestrator/tests/orchestratorRun.test.ts
    mode: owned
  - path: apps/cli/tests/cli.test.ts
    mode: owned
risk: high
verify:
  - bun test packages/orchestrator/tests/orchestratorRun.test.ts apps/cli/tests/cli.test.ts
  - git diff --check -- packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/orchestratorRun.test.ts apps/cli/tests/cli.test.ts
```

**Files:**
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/orchestrator/tests/orchestratorRun.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`

**Compatibility constraint:** The existing test
`apps/cli/tests/cli.test.ts` "run normalizes executable superpowers
implementation plans before dispatch" asserts
`expect(task?.risk).toBe("high")` on a recovered prose plan. This
assertion is load-bearing documentation of the Recovered Task Risk
Classification policy (see design) and MUST remain green. Adding new
intake-recovery assertions to `apps/cli/tests/cli.test.ts` is fine; do
not relax or delete the existing risk assertion.

- [ ] **Step 1: Add failing run lifecycle tests**

Add this test to `packages/orchestrator/tests/orchestratorRun.test.ts`:

```ts
  test("recovers bad-but-safe plan intake before dispatch", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-intake-root-"));
    const workspace = initSourceCheckout("waygent-intake-source-");
    const planPath = join(workspace, "plan.md");
    writeFileSync(planPath, `
# Recoverable Plan

### Task 1: Update README

Change \`README.md\` to mention intake recovery.

Run:

\`\`\`bash
git diff --check -- README.md
\`\`\`
`);

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_intake_recovered",
      plan_path: "plan.md",
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    expect(result.events.map((event) => event.event_type)).toContain("platform.intake_recovery_started");
    expect(result.events.map((event) => event.event_type)).toContain("platform.intake_recovery_completed");
    const state = readRunStateV2(root, "run_intake_recovered");
    expect(state.intake_recovery).toMatchObject({
      status: "recovered",
      can_start: true,
      normalized_plan_ref: "artifacts/intake/normalized-plan.md",
      recovery_report_ref: "artifacts/intake/recovery-report.json"
    });
    await expect(Bun.file(join(root, "run_intake_recovered", "artifacts", "intake", "normalized-plan.md")).exists()).resolves.toBe(true);
    await expect(Bun.file(join(root, "run_intake_recovered", "artifacts", "intake", "recovery-report.json")).exists()).resolves.toBe(true);
  });

  test("records decision-required intake blockers instead of throwing raw parser errors", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-intake-blocked-root-"));
    const workspace = initSourceCheckout("waygent-intake-blocked-source-");
    writeFileSync(join(workspace, "plan.md"), `
# Unsafe Plan

### Task 1: Reset source

Modify \`README.md\`.

\`\`\`bash
rm -rf .
\`\`\`
`);

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_intake_blocked",
      plan_path: "plan.md",
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    expect(result.events.map((event) => event.event_type)).toContain("platform.intake_decision_required");
    const state = readRunStateV2(root, "run_intake_blocked");
    expect(state.status).toBe("blocked");
    expect(state.intake_recovery).toMatchObject({
      status: "decision_required",
      can_start: false
    });
    expect(state.apply).toMatchObject({ status: "blocked", reason: "intake_decision_required" });
  });
```

Add this CLI assertion to `apps/cli/tests/cli.test.ts` after the current incomplete-plan rejection test:

```ts
  test("run reports intake recovery artifacts for recoverable prose plans", async () => {
    const workspace = initSourceCheckout("waygent-cli-intake-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-cli-intake-root-"));
    writeFileSync(join(workspace, "plan.md"), `
# Recoverable CLI Plan

### Task 1: Update README

Modify \`README.md\`.

\`\`\`bash
git diff --check -- README.md
\`\`\`
`);

    const result = await runCli([
      "run",
      "--provider", "fake",
      "--workspace", workspace,
      "--root", root,
      "--run", "run_cli_intake",
      "--plan", "plan.md"
    ]);

    expect(result).toMatchObject({ run_id: "run_cli_intake" });
    const state = readRunStateV2(root, "run_cli_intake");
    expect(state.intake_recovery?.status).toBe("recovered");
  });
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `bun test packages/orchestrator/tests/orchestratorRun.test.ts apps/cli/tests/cli.test.ts`

Expected: FAIL because `runWaygent` still calls `normalizeWaygentPlanInput()` directly and does not write intake artifacts.

- [ ] **Step 3: Integrate recovery into `runWaygent`**

Modify imports in `packages/orchestrator/src/orchestrator.ts`:

```ts
import { recoverWaygentPlanInput } from "./intakeRecovery";
```

Replace:

```ts
  const normalizedPlan = normalizeWaygentPlanInput(planInput);
```

with:

```ts
  const intake = recoverWaygentPlanInput({
    markdown: planInput.markdown,
    path: planInput.path,
    workspace,
    spec_markdown: specInput.markdown,
    spec_path: specInput.path
  });
  const normalizedPlan = intake.normalized_plan;
```

Remove the now-unused `normalizeWaygentPlanInput` import.

- [ ] **Step 4: Write intake artifacts before preflight**

Immediately after `const normalizedPlan = intake.normalized_plan;`, add:

```ts
  const intakeReportArtifact = intake.report.status === "not_needed"
    ? null
    : writeArtifact(paths.root, "intake/recovery-report.json", `${JSON.stringify(intake.report, null, 2)}\n`, "application/json");
  const intakeNormalizedArtifact = intake.report.can_start && intake.report.status !== "not_needed"
    ? writeArtifact(paths.root, "intake/normalized-plan.md", `${normalizedPlan.markdown.trimEnd()}\n`, "text/markdown")
    : null;
  const intakeRecovery = intake.report.status === "not_needed"
    ? intake.report
    : {
      ...intake.report,
      normalized_plan_ref: intakeNormalizedArtifact?.path || intake.report.normalized_plan_ref,
      recovery_report_ref: intakeReportArtifact?.path || intake.report.recovery_report_ref
    };
```

- [ ] **Step 5: Add an intake event helper**

Add this helper near the other local helper functions in `packages/orchestrator/src/orchestrator.ts`:

```ts
function appendIntakeEvents(
  context: RunExecutionContext,
  runId: string,
  planPath: string | null,
  specPath: string | null,
  intakeRecovery: WaygentRunStateV2["intake_recovery"]
): void {
  if (!intakeRecovery || intakeRecovery.status === "not_needed") return;
  context.appendEvent((sequence) => buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "platform.intake_recovery_started",
    phase: "preflight",
    outcome: "running",
    summary: "Plan/spec intake recovery started.",
    payload: {
      plan_path: planPath,
      spec_path: specPath,
      findings: intakeRecovery.findings.map((finding) => finding.code)
    },
    trust_impact: "neutral"
  }));
  context.appendEvent((sequence) => buildRunEvent({
    run_id: runId,
    sequence,
    event_type: intakeRecovery.can_start ? "platform.intake_recovery_completed" : "platform.intake_decision_required",
    phase: "preflight",
    outcome: intakeRecovery.can_start ? "success" : "blocked",
    summary: intakeRecovery.can_start ? "Plan/spec intake recovery completed." : "Plan/spec intake requires an operator decision.",
    payload: intakeRecovery,
    trust_impact: intakeRecovery.can_start ? "supports_success" : "requires_review"
  }));
}
```

Call the helper immediately after the existing `platform.run_started` event is appended:

```ts
  appendIntakeEvents(context, runId, planInput.path, specInput.path, intakeRecovery);
```

This preserves `platform.run_started` as the first event and records intake recovery before plan preflight and task loading events.

- [ ] **Step 6: Block safely when intake requires a decision**

Before `runPlanPreflight(...)`, add a blocked-run return path:

```ts
  if (!intakeRecovery.can_start) {
    const startedAt = new Date().toISOString();
    const blockedState: WaygentRunStateV2 = {
      schema: "waygent.run_state.v2",
      run_id: runId,
      workspace,
      source_branch: null,
      worktree_root: options.worktree_root || join(options.root, "worktrees"),
      run_root: paths.root,
      artifact_root: paths.artifacts,
      state_path: join(paths.root, "state.json"),
      event_journal_path: paths.events,
      plan_path: planInput.path,
      spec_path: specInput.path,
      provider_profile: providerProfile,
      intake_recovery: intakeRecovery,
      status: "blocked",
      lifecycle_outcome: "blocked",
      current_phase: "preflight",
      tasks: {},
      safe_waves: [],
      provider_attempts: [],
      reviews: [],
      verification: [],
      recovery: [],
      apply: { status: "blocked", reason: "intake_decision_required" },
      context: { snapshot_path: null, basis_hash: null },
      drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
      completion_audit: null,
      timestamps: { started_at: startedAt, updated_at: startedAt, completed_at: startedAt }
    };
    const blockedContext = createRunExecutionContext({ root: options.root, state: blockedState, next_sequence: 1 });
    blockedContext.flushState();
    blockedContext.appendEvent((sequence) => buildRunEvent({
      run_id: runId,
      sequence,
      event_type: "platform.run_started",
      phase: "platform",
      outcome: "blocked",
      summary: "Run opened but intake requires an operator decision.",
      payload: { plan: planInput.path, spec: specInput.path, profile: providerProfile },
      trust_impact: "requires_review"
    }));
    appendIntakeEvents(blockedContext, runId, planInput.path, specInput.path, intakeRecovery);
    writeLatestRunId(options.root, runId);
    return finalizeRun(options.root, paths, runId, emptyProjection(), blockedContext.nextSequence());
  }
```

Add this helper near `appendIntakeEvents`:

```ts
function emptyProjection(): ReturnType<typeof buildDurableProjection> {
  return {
    ready_tasks: [],
    safe_wave: [],
    withheld_tasks: [],
    blocked_node: null,
    projection_status: "blocked",
    next_automatic_action: null,
    required_human_decision: null
  } as ReturnType<typeof buildDurableProjection>;
}
```

- [ ] **Step 7: Persist recovered intake on normal run state**

In `initialState`, add:

```ts
    intake_recovery: intakeRecovery,
```

In the `platform.run_started` payload, add:

```ts
      intake_recovery: {
        status: intakeRecovery.status,
        can_start: intakeRecovery.can_start,
        normalized_plan_ref: intakeRecovery.normalized_plan_ref,
        recovery_report_ref: intakeRecovery.recovery_report_ref
      },
```

- [ ] **Step 8: Run tests and commit**

Run: `bun test packages/orchestrator/tests/orchestratorRun.test.ts apps/cli/tests/cli.test.ts`

Expected: PASS.

Run: `git diff --check -- packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/orchestratorRun.test.ts apps/cli/tests/cli.test.ts`

Expected: no output.

Commit:

```bash
git add packages/orchestrator/src/orchestrator.ts packages/orchestrator/tests/orchestratorRun.test.ts apps/cli/tests/cli.test.ts
git commit -m "feat: recover Waygent plan intake before dispatch"
```

---

### Task 4: Operator Workbench v2 Projection and Surfaces

```yaml waygent-task
id: task_4_operator_workbench_intake_surface
title: Operator Workbench Intake Surface
dependencies: [task_3_run_lifecycle_integration]
file_claims:
  - path: packages/lens-projectors/src/operatorDecision.ts
    mode: owned
  - path: packages/lens-projectors/tests/operatorDecision.test.ts
    mode: owned
  - path: apps/api/src/server.ts
    mode: owned
  - path: apps/api/tests/api.test.ts
    mode: owned
  - path: apps/console/src/uiModel.ts
    mode: owned
  - path: apps/console/src/uiModel.test.ts
    mode: owned
risk: high
verify:
  - bun test packages/lens-projectors/tests/operatorDecision.test.ts apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts
  - git diff --check -- packages/lens-projectors/src/operatorDecision.ts packages/lens-projectors/tests/operatorDecision.test.ts apps/api/src/server.ts apps/api/tests/api.test.ts apps/console/src/uiModel.ts apps/console/src/uiModel.test.ts
```

**Files:**
- Modify: `packages/lens-projectors/src/operatorDecision.ts`
- Modify: `packages/lens-projectors/tests/operatorDecision.test.ts`
- Modify: `apps/api/src/server.ts`
- Modify: `apps/api/tests/api.test.ts`
- Modify: `apps/console/src/uiModel.ts`
- Modify: `apps/console/src/uiModel.test.ts`

- [ ] **Step 1: Add failing operator projection tests**

Add these tests to `packages/lens-projectors/tests/operatorDecision.test.ts`:

```ts
  test("surfaces recovered intake artifacts without blocking execution", () => {
    const projection = projectOperatorDecisionFromState({
      state: makeState({
        intake_recovery: {
          status: "recovered",
          started_at: "2026-05-23T00:00:00.000Z",
          completed_at: "2026-05-23T00:00:01.000Z",
          normalized_plan_ref: "artifacts/intake/normalized-plan.md",
          recovery_report_ref: "artifacts/intake/recovery-report.json",
          findings: [{ code: "task_body_not_yaml", severity: "warning", message: "Recovered prose task.", task_id: "task_a", evidence_refs: ["plan:task-1"] }],
          repair_actions: [{ action: "deterministic_markdown_intake_repair", status: "applied", reason: "Recovered markdown task.", evidence_refs: ["artifacts/intake/normalized-plan.md"] }],
          can_start: true,
          confidence: "deterministic",
          question: null
        }
      }),
      events: []
    });

    expect(projection.intake_recovery).toMatchObject({
      status: "recovered",
      can_start: true,
      finding_codes: ["task_body_not_yaml"],
      artifact_refs: ["artifacts/intake/normalized-plan.md", "artifacts/intake/recovery-report.json"]
    });
    expect(projection.evidence_packet.artifact_refs).toContain("artifacts/intake/recovery-report.json");
  });

  test("makes decision-required intake the primary blocker", () => {
    const projection = projectOperatorDecisionFromState({
      state: makeState({
        status: "blocked",
        lifecycle_outcome: "blocked",
        current_phase: "preflight",
        intake_recovery: {
          status: "decision_required",
          started_at: "2026-05-23T00:00:00.000Z",
          completed_at: "2026-05-23T00:00:01.000Z",
          normalized_plan_ref: null,
          recovery_report_ref: "artifacts/intake/recovery-report.json",
          findings: [{ code: "destructive_command_candidate", severity: "blocking", message: "Destructive command candidate.", task_id: "task_a", evidence_refs: ["plan:task-1"] }],
          repair_actions: [{ action: "deterministic_markdown_intake_repair", status: "blocked", reason: "High-risk ambiguity prevents execution.", evidence_refs: ["plan:task-1"] }],
          can_start: false,
          confidence: "blocked",
          question: "The plan contains a destructive command candidate. Confirm the intended safe replacement before execution."
        },
        apply: { status: "blocked", reason: "intake_decision_required" }
      }),
      events: []
    });

    expect(projection.primary_blocker).toMatchObject({
      code: "intake_decision_required",
      severity: "blocking",
      recommended_action_ids: ["request_user_input", "open_raw_evidence"]
    });
    expect(projection.allowed_actions.map((action) => action.id)).toContain("request_user_input");
    expect(projection.blocked_actions).toContainEqual(expect.objectContaining({
      id: "apply_run",
      reason: expect.stringContaining("intake decision")
    }));
  });
```

- [ ] **Step 2: Update operator projection**

In `packages/lens-projectors/src/operatorDecision.ts`, add `OperatorIntakeRecoverySummary` to the type import. Add `intake_decision_required` to `blockerPriority` with priority `15`.

Add this helper near the evidence helpers:

```ts
function intakeArtifactRefs(state: WaygentRunStateV2): string[] {
  const intake = state.intake_recovery;
  if (!intake) return [];
  return [intake.normalized_plan_ref, intake.recovery_report_ref].filter((ref): ref is string => Boolean(ref));
}

function intakeSummary(state: WaygentRunStateV2): OperatorIntakeRecoverySummary | undefined {
  const intake = state.intake_recovery;
  if (!intake || intake.status === "not_needed") return undefined;
  return {
    status: intake.status,
    can_start: intake.can_start,
    confidence: intake.confidence,
    finding_codes: intake.findings.map((finding) => finding.code),
    artifact_refs: intakeArtifactRefs(state),
    question: intake.question
  };
}

function intakeBlockers(state: WaygentRunStateV2): OperatorBlocker[] {
  const intake = state.intake_recovery;
  if (!intake || intake.can_start) return [];
  return [makeBlocker({
    code: "intake_decision_required",
    title: "Intake decision required",
    summary: intake.question || "Waygent could not safely recover an executable plan from the supplied documents.",
    severity: "blocking",
    evidenceRefs: intakeArtifactRefs(state).length > 0 ? intakeArtifactRefs(state) : intake.findings.flatMap((finding) => finding.evidence_refs),
    missingRefs: [],
    recommendedActionIds: ["request_user_input", "open_raw_evidence"]
  })];
}
```

Update `evidencePacketFromState` to append `...intakeArtifactRefs(state)` to `artifact_refs`.

Update `blockersFromState` to include `...intakeBlockers(state)` before task failure blockers.

Add `intake_recovery: intakeSummary(state),` to the returned projection object.

Update `blockedActionsFor` so `primaryBlocker?.code === "intake_decision_required"` blocks `apply_run` with reason `"Apply is blocked until the intake decision is resolved."`.

- [ ] **Step 3: Run the projector tests**

Run: `bun test packages/lens-projectors/tests/operatorDecision.test.ts`

Expected: PASS.

- [ ] **Step 4: Add API and Console tests for intake summary**

In `apps/console/src/uiModel.test.ts`, add this test near the Workbench detail test:

```ts
  test("renders intake recovery summary in Workbench detail", () => {
    const model = buildRunDetailModel({
      run_id: "run_intake",
      status: "blocked",
      trust_status: "insufficient_evidence",
      apply_status: "blocked",
      total_events: 2,
      last_event_type: "platform.intake_decision_required",
      safe_wave: [],
      failures: [],
      timeline: [],
      operator_decision: {
        schema: "waygent.operator_decision.v1",
        run_id: "run_intake",
        generated_at: "2026-05-23T00:00:00.000Z",
        status_summary: {
          display_status: "blocked",
          runtime_status: "blocked",
          lifecycle_outcome: "blocked",
          current_phase: "preflight",
          active_tasks: 0,
          completed_tasks: 0,
          blocked_tasks: 0,
          apply_status: "blocked",
          summary: "run_intake is blocked by intake_decision_required."
        },
        primary_blocker: {
          code: "intake_decision_required",
          title: "Intake decision required",
          summary: "Confirm safe replacement.",
          severity: "blocking",
          evidence_refs: ["artifacts/intake/recovery-report.json"],
          missing_refs: [],
          recommended_action_ids: ["request_user_input", "open_raw_evidence"]
        },
        secondary_blockers: [],
        allowed_actions: [],
        blocked_actions: [],
        evidence_packet: {
          state_refs: ["state:state.json"],
          event_refs: [],
          artifact_refs: ["artifacts/intake/recovery-report.json"],
          verification_refs: [],
          checkpoint_refs: [],
          projection_refs: [],
          missing_refs: [],
          redaction_notes: []
        },
        ai_handoff: {
          purpose: "summarize_blocker",
          prompt_summary: "Summarize intake blocker.",
          run_id: "run_intake",
          current_status: "blocked",
          primary_blocker: "intake_decision_required",
          secondary_blockers: [],
          allowed_action_ids: [],
          blocked_action_ids: [],
          constraints: ["Do not apply patches."],
          evidence_refs: ["artifacts/intake/recovery-report.json"],
          missing_evidence: [],
          raw_fallback_refs: [],
          safety_notes: ["Waygent runtime remains apply authority."]
        },
        confidence: "deterministic",
        unknown_reasons: [],
        intake_recovery: {
          status: "decision_required",
          can_start: false,
          confidence: "blocked",
          finding_codes: ["destructive_command_candidate"],
          artifact_refs: ["artifacts/intake/recovery-report.json"],
          question: "Confirm safe replacement."
        },
        source_projection_refs: {
          run_state_v2: "state:state.json",
          apply_readiness: "waygent.apply_readiness",
          execution_explanation: "waygent.execution_explanation.v1",
          operational_maturity: "waygent.operational_maturity.v1"
        }
      }
    });

    expect(model.operator_decision?.intake_recovery).toMatchObject({
      status: "decision_required",
      question: "Confirm safe replacement."
    });
    expect(model.raw_evidence_refs).toContain("artifacts/intake/recovery-report.json");
  });
```

In `apps/api/tests/api.test.ts`, extend the real-run detail fixture test or add a new one that creates a state with `intake_recovery` and asserts `detail.operator_decision.intake_recovery.status === "recovered"`.

- [ ] **Step 5: Update Console model raw evidence refs**

In `apps/console/src/uiModel.ts`, update `rawEvidenceRefsFromDecision` or the equivalent function that builds `raw_evidence_refs` so it includes:

```ts
...(decision?.intake_recovery?.artifact_refs || [])
```

Do not add a separate Console-only blocker calculation.

- [ ] **Step 6: Run tests and commit**

Run: `bun test packages/lens-projectors/tests/operatorDecision.test.ts apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts`

Expected: PASS.

Run: `git diff --check -- packages/lens-projectors/src/operatorDecision.ts packages/lens-projectors/tests/operatorDecision.test.ts apps/api/src/server.ts apps/api/tests/api.test.ts apps/console/src/uiModel.ts apps/console/src/uiModel.test.ts`

Expected: no output.

Commit:

```bash
git add packages/lens-projectors/src/operatorDecision.ts packages/lens-projectors/tests/operatorDecision.test.ts apps/api/src/server.ts apps/api/tests/api.test.ts apps/console/src/uiModel.ts apps/console/src/uiModel.test.ts
git commit -m "feat: surface intake recovery in Workbench"
```

---

### Task 5: Fixture-Lab Regression Harness

```yaml waygent-task
id: task_5_fixture_lab_regression_harness
title: Fixture-Lab Regression Harness
dependencies: [task_4_operator_workbench_intake_surface]
file_claims:
  - path: tests/fixtures/waygent-lab/recoverable-prose-plan.md
    mode: owned
  - path: tests/fixtures/waygent-lab/unsafe-destructive-plan.md
    mode: owned
  - path: tests/fixtures/waygent-lab/malformed-provider-with-worker-result.stdout.txt
    mode: owned
  - path: tests/integration/waygent-fixture-lab.test.ts
    mode: owned
  - path: package.json
    mode: owned
risk: medium
verify:
  - bun test tests/integration/waygent-fixture-lab.test.ts
  - git diff --check -- tests/fixtures/waygent-lab/recoverable-prose-plan.md tests/fixtures/waygent-lab/unsafe-destructive-plan.md tests/fixtures/waygent-lab/malformed-provider-with-worker-result.stdout.txt tests/integration/waygent-fixture-lab.test.ts package.json
```

**Files:**
- Create: `tests/fixtures/waygent-lab/recoverable-prose-plan.md`
- Create: `tests/fixtures/waygent-lab/unsafe-destructive-plan.md`
- Create: `tests/fixtures/waygent-lab/malformed-provider-with-worker-result.stdout.txt`
- Create: `tests/integration/waygent-fixture-lab.test.ts`
- Modify: `package.json`

- [ ] **Step 1: Add lab fixtures**

Create `tests/fixtures/waygent-lab/recoverable-prose-plan.md`:

````md
# Recoverable Operator Plan

### Task 1: Update README

Modify `README.md` to mention intake recovery.

```bash
git diff --check -- README.md
```
````

Create `tests/fixtures/waygent-lab/unsafe-destructive-plan.md`:

````md
# Unsafe Operator Plan

### Task 1: Reset workspace

Modify `README.md`.

```bash
git reset --hard HEAD
```
````

Create `tests/fixtures/waygent-lab/malformed-provider-with-worker-result.stdout.txt`:

````text
Implementation complete.

```bash
echo not-json
```

```json
{"schema":"runway.worker_result.v1","task_id":"task_demo","candidate_id":"candidate_task_demo","status":"completed","changed_files":["README.md"],"summary":"Recovered worker JSON from second fence.","evidence":{"usage":{"input_tokens":1,"output_tokens":2,"cached_read_tokens":0,"cached_write_tokens":0}}}
```
````

- [ ] **Step 2: Add the integration test**

Create `tests/integration/waygent-fixture-lab.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runWaygent, readRunStateV2 } from "@waygent/orchestrator";
import { normalizeProcessOutput } from "@waygent/provider-adapters";
import { projectOperatorDecisionFromState } from "@waygent/lens-projectors";
import { readEvents } from "@waygent/lens-store";

function initSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "before\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
  return workspace;
}

function fixture(name: string): string {
  return readFileSync(join(import.meta.dir, "..", "fixtures", "waygent-lab", name), "utf8");
}

describe("Waygent Fixture-Lab", () => {
  test("recoverable prose plan starts and records intake artifacts", async () => {
    const workspace = initSourceCheckout("waygent-lab-recoverable-");
    const root = mkdtempSync(join(tmpdir(), "waygent-lab-recoverable-root-"));
    mkdirSync(join(workspace, "docs", "superpowers", "plans"), { recursive: true });
    writeFileSync(join(workspace, "docs", "superpowers", "plans", "recoverable.md"), fixture("recoverable-prose-plan.md"));

    await runWaygent({
      root,
      workspace,
      run_id: "run_lab_recoverable",
      plan_path: "recoverable.md",
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_lab_recoverable");
    const events = readEvents(join(root, "run_lab_recoverable", "events.jsonl"));
    const operator = projectOperatorDecisionFromState({ state, events });

    expect(state.intake_recovery?.status).toBe("recovered");
    expect(operator.intake_recovery?.status).toBe("recovered");
    expect(operator.evidence_packet.artifact_refs).toContain("artifacts/intake/recovery-report.json");
  });

  test("unsafe plan asks for user decision and never dispatches a worker", async () => {
    const workspace = initSourceCheckout("waygent-lab-unsafe-");
    const root = mkdtempSync(join(tmpdir(), "waygent-lab-unsafe-root-"));
    writeFileSync(join(workspace, "unsafe.md"), fixture("unsafe-destructive-plan.md"));

    await runWaygent({
      root,
      workspace,
      run_id: "run_lab_unsafe",
      plan_path: "unsafe.md",
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_lab_unsafe");
    const events = readEvents(join(root, "run_lab_unsafe", "events.jsonl"));
    const operator = projectOperatorDecisionFromState({ state, events });

    expect(events.map((event) => event.event_type)).not.toContain("runway.worker_result");
    expect(state.intake_recovery?.status).toBe("decision_required");
    expect(operator.primary_blocker?.code).toBe("intake_decision_required");
  });

  test("malformed provider fixture still normalizes worker result from second json fence", () => {
    const output = normalizeProcessOutput("claude", "task_demo", "candidate_task_demo", {
      exitCode: 0,
      stdout: fixture("malformed-provider-with-worker-result.stdout.txt"),
      stderr: "",
      timedOut: false,
      startedAt: "2026-05-23T00:00:00.000Z",
      completedAt: "2026-05-23T00:00:01.000Z"
    });

    expect(output.worker).toMatchObject({
      task_id: "task_demo",
      status: "completed",
      summary: "Recovered worker JSON from second fence."
    });
  });
});
```

- [ ] **Step 3: Add a package script**

In root `package.json`, add:

```json
"waygent:fixture-lab": "bun test tests/integration/waygent-fixture-lab.test.ts"
```

Keep the existing script order readable; place it near `waygent:scenarios` and `waygent:dogfood`.

- [ ] **Step 4: Run the lab test and commit**

Run: `bun run waygent:fixture-lab`

Expected: PASS.

Run: `git diff --check -- tests/fixtures/waygent-lab/recoverable-prose-plan.md tests/fixtures/waygent-lab/unsafe-destructive-plan.md tests/fixtures/waygent-lab/malformed-provider-with-worker-result.stdout.txt tests/integration/waygent-fixture-lab.test.ts package.json`

Expected: no output.

Commit:

```bash
git add tests/fixtures/waygent-lab/recoverable-prose-plan.md tests/fixtures/waygent-lab/unsafe-destructive-plan.md tests/fixtures/waygent-lab/malformed-provider-with-worker-result.stdout.txt tests/integration/waygent-fixture-lab.test.ts package.json
git commit -m "test: add Waygent intake fixture lab"
```

---

### Task 6: Docs, Skill Surface, and Final Verification

```yaml waygent-task
id: task_6_docs_skill_final_verification
title: Docs Skill Surface and Final Verification
dependencies: [task_5_fixture_lab_regression_harness]
file_claims:
  - path: docs/operations/waygent.md
    mode: owned
  - path: docs/contracts/run-state.md
    mode: owned
  - path: docs/operations/verification.md
    mode: owned
  - path: skills/waygent/SKILL.md
    mode: owned
  - path: skills/waygent/evals/check_skill_contract.py
    mode: owned
  - path: graphify-out/GRAPH_REPORT.md
    mode: owned
  - path: graphify-out/graph.json
    mode: owned
risk: medium
verify:
  - skills/waygent/evals/run.sh
  - bun run waygent:fixture-lab
  - bun run waygent:scenarios
  - bun run waygent:dogfood
  - bun run check
  - git diff --check
```

**Files:**
- Modify: `docs/operations/waygent.md`
- Modify: `docs/contracts/run-state.md`
- Modify: `docs/operations/verification.md`
- Modify: `skills/waygent/SKILL.md`
- Modify: `skills/waygent/evals/check_skill_contract.py`
- Modify: `graphify-out/GRAPH_REPORT.md`
- Modify: `graphify-out/graph.json`

- [ ] **Step 1: Document operator intake behavior**

In `docs/operations/waygent.md`, add a subsection under `### Run Preflight`:

```md
### Intake Recovery

Waygent attempts strict plan parsing first. If the supplied design or
implementation document is clearly intended for execution but does not match
the executable `waygent-task` shape, Waygent runs deterministic intake recovery
before plan preflight.

Recoverable examples include prose task bodies, `### Task` headings, file
claims written as path references, and safe verification commands in fenced
shell blocks. Waygent writes `artifacts/intake/normalized-plan.md` and
`artifacts/intake/recovery-report.json`, then continues through the normal
preflight, scheduling, verification, checkpoint, and apply-readiness gates.

High-risk intake blockers still stop execution and surface
`intake_decision_required`. These include destructive commands, multiple
matching plan/spec candidates, path escapes, missing verification for
source-mutating work, and apply-like mutation before verification evidence.
```

- [ ] **Step 2: Document run-state fields**

In `docs/contracts/run-state.md`, add this bullet under `Runtime Improvement Fields`:

```md
- `intake_recovery`: records strict parser/preflight shape failures, automatic
  repair actions, normalized plan artifact refs, recovery report refs, and
  whether execution may start without user input.
```

- [ ] **Step 3: Document verification command**

In `docs/operations/verification.md`, add:

```md
`bun run waygent:fixture-lab` replays recoverable and unsafe intake examples.
It proves that bad-but-recoverable plan/spec shapes start safely, unsafe input
asks for a user decision, and provider-output parser regressions remain covered.
```

- [ ] **Step 4: Update the Waygent skill**

In `skills/waygent/SKILL.md`, add this stop-rule paragraph near the existing stop rules:

```md
- If a run reports `intake_decision_required`, explain the specific blocker
  and ask only the short question from the operator decision. Do not rewrite
  the plan from chat unless the user approves the change.
- If intake recovery reports `recovered`, proceed with the run result and
  mention the normalized plan and recovery report artifact refs when useful.
```

- [ ] **Step 5: Extend the skill eval**

In `skills/waygent/evals/check_skill_contract.py`, add required phrases:

```py
required_skill_phrases.extend([
    "intake_decision_required",
    "normalized plan",
    "recovery report",
])
```

If the file uses a tuple instead of a list, add those three strings to the same literal.

- [ ] **Step 6: Refresh Graphify**

Run: `graphify update .`

Expected: command exits 0 and updates `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.json`.

- [ ] **Step 7: Run final verification**

Run these commands in order:

```bash
skills/waygent/evals/run.sh
bun run waygent:fixture-lab
bun run waygent:scenarios
bun run waygent:dogfood
bun run check
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 8: Commit final docs and graph updates**

Commit:

```bash
git add docs/operations/waygent.md docs/contracts/run-state.md docs/operations/verification.md skills/waygent/SKILL.md skills/waygent/evals/check_skill_contract.py graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "docs: document Waygent intake recovery"
```

---

## Full Verification Checklist

Run after all tasks are complete:

```bash
bun test packages/contracts/tests/contracts.test.ts
bun test packages/orchestrator/tests/intakeRecovery.test.ts packages/orchestrator/tests/orchestratorRun.test.ts apps/cli/tests/cli.test.ts
bun test packages/lens-projectors/tests/operatorDecision.test.ts apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts
bun run waygent:fixture-lab
bun run waygent:scenarios
bun run waygent:dogfood
skills/waygent/evals/run.sh
bun run check
git diff --check
```

Expected: every command exits 0. If `graphify update .` changes tracked graph files after verification, restage those files and rerun `git diff --check` before the final commit.

## Self-Review Notes

- Spec coverage: Tasks 1-4 implement the operator read model and intake recovery; Task 5 implements Fixture-Lab; Task 6 documents operator behavior and verifies the skill surface.
- Scope control: The plan does not introduce `waygent.run_state.v3`, legacy Python AgentLens, or KWS CPE/CME routing.
- Safety control: Destructive commands, ambiguous candidates, path escapes, unverified source mutation, and apply-like pre-verification mutation remain blocking user-decision cases.
- Efficiency control: Strict parsing and deterministic repair run before any AI/provider repair seam, and safe-wave scheduling remains the execution boundary.
