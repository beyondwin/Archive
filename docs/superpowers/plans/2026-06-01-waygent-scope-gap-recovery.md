# Waygent Scope Gap Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Waygent detect generated-output claim gaps, classify structural diff-scope failures, stop wasteful retries, and surface exact scope amendments to the operator.

**Architecture:** Add a pure generated-output detector and richer diff-scope classification, then wire those signals into recovery, orchestration, and operator projections. Runtime safety stays strict: no checkpoint, dependency release, or apply occurs until claims and diff scope are valid.

**Tech Stack:** Bun, TypeScript, `@waygent/orchestrator`, `@waygent/context-packer`, `@waygent/lens-projectors`, fake-provider scenario fixtures, filesystem JSON/JSONL artifacts.

---

## Source Spec

- Design spec: `docs/superpowers/specs/2026-06-01-waygent-scope-gap-recovery-design.md`
- Incident evidence: Waygent run `readmates_contract_visual_reading_momentum_umbrella_20260601_060852`
- Primary failure: `diff_scope_failed` with `changed_file_outside_allowed_globs`
- Violating files:
  - `front/tests/unit/__fixtures__/zod-schemas/admin-analytics-overview.json`
  - `front/tests/unit/__fixtures__/zod-schemas/current-session.json`

## File Structure Map

- `packages/orchestrator/src/generatedOutputs.ts`: new pure detector for generated output signals and missing generated claims.
- `packages/orchestrator/tests/generatedOutputs.test.ts`: TDD coverage for detector behavior.
- `packages/orchestrator/src/diffScope.ts`: extend scope validation result with `scope_failure_kind` and recommended amendments.
- `packages/orchestrator/tests/diffScope.test.ts`: lock structural scope classifications.
- `packages/orchestrator/src/recoveryExecutor.ts`: stop automatic retry for structural scope failures.
- `packages/orchestrator/tests/recoveryExecutor.test.ts`: prove `generated_artifact_unclaimed` and repeated identical violations request decision.
- `packages/orchestrator/src/taskExecutor.ts`: pass detector context into diff scope validation and emit richer event payloads.
- `packages/orchestrator/src/orchestrator.ts`: run deterministic pre-dispatch scope-gap check after task normalization.
- `packages/lens-projectors/src/operatorDecision.ts`: show missing generated claims in operator-facing projections.
- `packages/lens-projectors/tests/operatorDecision.test.ts`: assert explanation data for scope amendment decisions.
- `packages/testkit/src/waygentScenarioHarness.ts`: add scenario support for generated output claim gaps.
- `tests/waygent-scenarios/generated-fixture-claim-gap.json`: deterministic regression scenario.
- `docs/operations/plan-authoring.md`: document generated artifact claims for plan authors.
- `docs/operations/recovery.md`: document structural scope failures and recovery behavior.

## Implementation Plan

### Task 1: Generated Output Detector

```yaml waygent-task
id: task_1_generated_output_detector
title: Generated output detector
dependencies: []
file_claims:
  - path: packages/orchestrator/src/generatedOutputs.ts
    mode: owned
  - path: packages/orchestrator/tests/generatedOutputs.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/generatedOutputs.test.ts
```

**Files:**
- Create: `packages/orchestrator/src/generatedOutputs.ts`
- Create: `packages/orchestrator/tests/generatedOutputs.test.ts`

- [ ] **Step 1: Write failing detector tests**

Create `packages/orchestrator/tests/generatedOutputs.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { detectGeneratedOutputs, findMissingGeneratedClaims } from "../src/generatedOutputs";

describe("detectGeneratedOutputs", () => {
  test("detects zod fixture export outputs from commands and plan text", () => {
    const result = detectGeneratedOutputs({
      task_id: "task_contracts",
      plan_text: "Run zod:export-fixtures and commit generated fixtures.",
      verification_commands: [
        "pnpm --dir front zod:export-fixtures",
        "git diff --exit-code front/tests/unit/__fixtures__/zod-schemas/"
      ]
    });

    expect(result.expected_outputs).toEqual([
      {
        path_glob: "front/tests/unit/__fixtures__/zod-schemas/*.json",
        reason: "zod fixture export writes frontend schema fixtures",
        evidence_refs: [
          "command:pnpm --dir front zod:export-fixtures",
          "command:git diff --exit-code front/tests/unit/__fixtures__/zod-schemas/",
          "plan:generated fixtures"
        ]
      }
    ]);
  });

  test("returns no outputs for unknown commands", () => {
    const result = detectGeneratedOutputs({
      task_id: "task_docs",
      plan_text: "Update operator docs.",
      verification_commands: ["git diff --check -- docs/operations/recovery.md"]
    });

    expect(result.expected_outputs).toEqual([]);
  });
});

describe("findMissingGeneratedClaims", () => {
  test("reports expected outputs not covered by owned claims", () => {
    const report = findMissingGeneratedClaims({
      run_id: "run_readmates",
      task_id: "task_contracts",
      existing_allowed_write_globs: [
        "front/scripts/export-zod-fixtures.ts",
        "server/src/test/kotlin/com/readmates/contract/FrontendZodSchemaContractTest.kt"
      ],
      expected_outputs: [
        {
          path_glob: "front/tests/unit/__fixtures__/zod-schemas/*.json",
          reason: "zod fixture export writes frontend schema fixtures",
          evidence_refs: ["command:pnpm --dir front zod:export-fixtures"]
        }
      ]
    });

    expect(report).toEqual({
      schema: "waygent.scope_gap_report.v1",
      run_id: "run_readmates",
      task_id: "task_contracts",
      status: "blocked",
      expected_outputs: [
        {
          path_glob: "front/tests/unit/__fixtures__/zod-schemas/*.json",
          reason: "zod fixture export writes frontend schema fixtures",
          evidence_refs: ["command:pnpm --dir front zod:export-fixtures"]
        }
      ],
      missing_claims: [
        {
          path: "front/tests/unit/__fixtures__/zod-schemas/*.json",
          mode: "owned",
          reason: "generated output is not covered by task writable claims"
        }
      ],
      existing_allowed_write_globs: [
        "front/scripts/export-zod-fixtures.ts",
        "server/src/test/kotlin/com/readmates/contract/FrontendZodSchemaContractTest.kt"
      ]
    });
  });
});
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
bun test packages/orchestrator/tests/generatedOutputs.test.ts
```

Expected: FAIL with module not found for `../src/generatedOutputs`.

- [ ] **Step 3: Implement detector**

Create `packages/orchestrator/src/generatedOutputs.ts`:

```ts
export interface ExpectedGeneratedOutput {
  path_glob: string;
  reason: string;
  evidence_refs: string[];
}

export interface GeneratedOutputDetectionInput {
  task_id: string;
  plan_text: string;
  verification_commands: string[];
}

export interface GeneratedOutputDetectionResult {
  task_id: string;
  expected_outputs: ExpectedGeneratedOutput[];
}

export interface ScopeGapReport {
  schema: "waygent.scope_gap_report.v1";
  run_id: string;
  task_id: string;
  status: "blocked";
  expected_outputs: ExpectedGeneratedOutput[];
  missing_claims: Array<{ path: string; mode: "owned"; reason: string }>;
  existing_allowed_write_globs: string[];
}

export function detectGeneratedOutputs(input: GeneratedOutputDetectionInput): GeneratedOutputDetectionResult {
  const evidence = new Set<string>();
  for (const command of input.verification_commands) {
    if (command.includes("zod:export-fixtures")) evidence.add(`command:${command}`);
    if (command.includes("front/tests/unit/__fixtures__/zod-schemas")) evidence.add(`command:${command}`);
  }
  const normalizedPlan = input.plan_text.toLowerCase();
  if (
    normalizedPlan.includes("export fixtures") ||
    normalizedPlan.includes("zod fixtures") ||
    normalizedPlan.includes("schema fixtures") ||
    normalizedPlan.includes("generated fixtures")
  ) {
    evidence.add("plan:generated fixtures");
  }

  if (evidence.size === 0) return { task_id: input.task_id, expected_outputs: [] };

  return {
    task_id: input.task_id,
    expected_outputs: [
      {
        path_glob: "front/tests/unit/__fixtures__/zod-schemas/*.json",
        reason: "zod fixture export writes frontend schema fixtures",
        evidence_refs: Array.from(evidence)
      }
    ]
  };
}

export function findMissingGeneratedClaims(input: {
  run_id: string;
  task_id: string;
  expected_outputs: ExpectedGeneratedOutput[];
  existing_allowed_write_globs: string[];
}): ScopeGapReport | null {
  const missing = input.expected_outputs
    .filter((output) => !input.existing_allowed_write_globs.some((claim) => coversGlob(claim, output.path_glob)))
    .map((output) => ({
      path: output.path_glob,
      mode: "owned" as const,
      reason: "generated output is not covered by task writable claims"
    }));

  if (missing.length === 0) return null;

  return {
    schema: "waygent.scope_gap_report.v1",
    run_id: input.run_id,
    task_id: input.task_id,
    status: "blocked",
    expected_outputs: input.expected_outputs,
    missing_claims: missing,
    existing_allowed_write_globs: input.existing_allowed_write_globs
  };
}

function coversGlob(claim: string, outputGlob: string): boolean {
  const normalizedClaim = normalizePath(claim);
  const normalizedOutput = normalizePath(outputGlob);
  if (normalizedClaim === normalizedOutput) return true;
  if (normalizedClaim.endsWith("/**")) return normalizedOutput.startsWith(normalizedClaim.slice(0, -"/**".length));
  if (normalizedOutput.endsWith("/*.json")) return normalizedClaim === normalizedOutput.slice(0, -"/*.json".length);
  return normalizedOutput.startsWith(`${normalizedClaim}/`);
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\.\/+/, "").replace(/\/+$/, "");
}
```

- [ ] **Step 4: Verify detector**

Run:

```bash
bun test packages/orchestrator/tests/generatedOutputs.test.ts
```

Expected: PASS.

### Task 2: Diff Scope Classification

```yaml waygent-task
id: task_2_diff_scope_classification
title: Diff scope classification
dependencies:
  - task_1_generated_output_detector
file_claims:
  - path: packages/orchestrator/src/diffScope.ts
    mode: owned
  - path: packages/orchestrator/tests/diffScope.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/diffScope.test.ts
```

**Files:**
- Modify: `packages/orchestrator/src/diffScope.ts`
- Modify: `packages/orchestrator/tests/diffScope.test.ts`

- [ ] **Step 1: Add failing classification tests**

Append to `packages/orchestrator/tests/diffScope.test.ts`:

```ts
test("classifies unclaimed generated artifacts", () => {
  expect(validateDiffScope({
    actual_changed_files: ["front/tests/unit/__fixtures__/zod-schemas/current-session.json"],
    claimed_changed_files: ["front/tests/unit/__fixtures__/zod-schemas/current-session.json"],
    allowed_write_globs: ["front/scripts/export-zod-fixtures.ts"],
    forbidden_write_globs: [".git/**", "node_modules/**"],
    expected_generated_outputs: [
      {
        path_glob: "front/tests/unit/__fixtures__/zod-schemas/*.json",
        reason: "zod fixture export writes frontend schema fixtures",
        evidence_refs: ["command:pnpm --dir front zod:export-fixtures"]
      }
    ]
  })).toMatchObject({
    ok: false,
    failure_class: "diff_scope_failed",
    reason: "changed_file_outside_allowed_globs",
    scope_failure_kind: "generated_artifact_unclaimed",
    recommended_scope_amendments: [
      {
        path: "front/tests/unit/__fixtures__/zod-schemas/current-session.json",
        mode: "owned",
        reason: "generated artifact is outside task writable claims",
        evidence_refs: ["command:pnpm --dir front zod:export-fixtures"]
      }
    ]
  });
});

test("classifies forbidden writes separately", () => {
  expect(validateDiffScope({
    actual_changed_files: [".git/config"],
    claimed_changed_files: [".git/config"],
    allowed_write_globs: [".git/config"],
    forbidden_write_globs: [".git/**"],
    expected_generated_outputs: []
  })).toMatchObject({
    ok: false,
    scope_failure_kind: "forbidden_write",
    recommended_scope_amendments: []
  });
});
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
bun test packages/orchestrator/tests/diffScope.test.ts
```

Expected: FAIL because `DiffScopeInput` does not accept `expected_generated_outputs` and the result lacks `scope_failure_kind`.

- [ ] **Step 3: Extend diff scope types and classification**

Modify `packages/orchestrator/src/diffScope.ts`:

```ts
import type { ExpectedGeneratedOutput } from "./generatedOutputs";

export type ScopeFailureKind =
  | "generated_artifact_unclaimed"
  | "provider_overreach"
  | "provider_claim_gap"
  | "forbidden_write";

export interface DiffScopeInput {
  actual_changed_files: string[];
  claimed_changed_files: string[];
  allowed_write_globs: string[];
  forbidden_write_globs: string[];
  expected_generated_outputs?: ExpectedGeneratedOutput[];
}
```

Extend the failed result type with:

```ts
scope_failure_kind: ScopeFailureKind;
recommended_scope_amendments: Array<{
  path: string;
  mode: "owned";
  reason: string;
  evidence_refs: string[];
}>;
```

Replace `failed(...)` calls so they pass a kind:

```ts
if (forbidden.length > 0) {
  return failed("changed_file_matches_forbidden_globs", "forbidden_write", changed_files, forbidden, input);
}

const outsideAllowed = changed_files.filter((file) => !matchesAny(file, input.allowed_write_globs));
if (outsideAllowed.length > 0) {
  const generated = outsideAllowed.filter((file) => matchesGeneratedOutput(file, input.expected_generated_outputs ?? []));
  return failed(
    "changed_file_outside_allowed_globs",
    generated.length > 0 ? "generated_artifact_unclaimed" : "provider_overreach",
    changed_files,
    outsideAllowed,
    input
  );
}

const missingClaim = changed_files.filter((file) => !matchesAny(file, input.claimed_changed_files));
if (missingClaim.length > 0) {
  return failed("changed_file_missing_provider_claim", "provider_claim_gap", changed_files, missingClaim, input);
}
```

Add helpers:

```ts
function matchesGeneratedOutput(file: string, outputs: ExpectedGeneratedOutput[]): boolean {
  return outputs.some((output) => matchesPattern(file, output.path_glob));
}

function amendmentEvidenceFor(file: string, outputs: ExpectedGeneratedOutput[]): string[] {
  return outputs
    .filter((output) => matchesPattern(file, output.path_glob))
    .flatMap((output) => output.evidence_refs);
}
```

Update `failed(...)`:

```ts
function failed(
  reason: Exclude<DiffScopeResult, { ok: true }>["reason"],
  scope_failure_kind: ScopeFailureKind,
  changed_files: string[],
  violating_files: string[],
  input: DiffScopeInput
): Exclude<DiffScopeResult, { ok: true }> {
  const expected = input.expected_generated_outputs ?? [];
  return {
    ok: false,
    failure_class: "diff_scope_failed",
    reason,
    scope_failure_kind,
    changed_files,
    violating_files,
    allowed_write_globs: input.allowed_write_globs.map(normalizePath).filter(Boolean),
    provider_claimed_changed_files: input.claimed_changed_files.map(normalizePath).filter(Boolean),
    recommended_scope_amendments: scope_failure_kind === "generated_artifact_unclaimed"
      ? violating_files.map((file) => ({
          path: file,
          mode: "owned" as const,
          reason: "generated artifact is outside task writable claims",
          evidence_refs: amendmentEvidenceFor(file, expected)
        }))
      : []
  };
}
```

- [ ] **Step 4: Verify diff scope tests**

Run:

```bash
bun test packages/orchestrator/tests/diffScope.test.ts
```

Expected: PASS.

### Task 3: Structural Recovery Policy

```yaml waygent-task
id: task_3_structural_recovery_policy
title: Structural recovery policy
dependencies:
  - task_2_diff_scope_classification
file_claims:
  - path: packages/orchestrator/src/recoveryExecutor.ts
    mode: owned
  - path: packages/orchestrator/tests/recoveryExecutor.test.ts
    mode: owned
risk: medium
verify:
  - bun test packages/orchestrator/tests/recoveryExecutor.test.ts
```

**Files:**
- Modify: `packages/orchestrator/src/recoveryExecutor.ts`
- Modify: `packages/orchestrator/tests/recoveryExecutor.test.ts`

- [ ] **Step 1: Add failing recovery tests**

Append to `packages/orchestrator/tests/recoveryExecutor.test.ts`:

```ts
test("requests decision for generated artifact scope gaps", () => {
  expect(nextRecoveryAction("diff_scope_failed", 0, {
    scope_failure_kind: "generated_artifact_unclaimed",
    prior_summary: "front/tests/unit/__fixtures__/zod-schemas/current-session.json is outside allowed_write_globs"
  })).toMatchObject({
    action: "request_decision",
    attempt_number: 1,
    max_attempts: 1
  });
});

test("allows one retry for ambiguous provider overreach", () => {
  expect(nextRecoveryAction("diff_scope_failed", 0, {
    scope_failure_kind: "provider_overreach",
    prior_summary: "README.md was changed outside allowed scope"
  })).toMatchObject({
    action: "retry_with_evidence",
    attempt_number: 1,
    max_attempts: 1
  });

  expect(nextRecoveryAction("diff_scope_failed", 1, {
    scope_failure_kind: "provider_overreach",
    prior_summary: "README.md was changed outside allowed scope"
  })).toMatchObject({
    action: "request_decision",
    attempt_number: 2,
    max_attempts: 1
  });
});
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
bun test packages/orchestrator/tests/recoveryExecutor.test.ts
```

Expected: FAIL because `NextRecoveryOptions` does not accept `scope_failure_kind`.

- [ ] **Step 3: Add scope-aware recovery decision**

Modify `packages/orchestrator/src/recoveryExecutor.ts`:

```ts
import type { ScopeFailureKind } from "./diffScope";

export interface NextRecoveryOptions {
  max_overrides?: Partial<Record<FailureClass, number>>;
  prior_summary?: string;
  scope_failure_kind?: ScopeFailureKind;
}
```

At the top of `nextRecoveryAction(...)`, before reading `DEFAULT_POLICY`, add:

```ts
if (failure_class === "diff_scope_failed" && options.scope_failure_kind) {
  if (
    options.scope_failure_kind === "generated_artifact_unclaimed" ||
    options.scope_failure_kind === "forbidden_write" ||
    options.scope_failure_kind === "provider_claim_gap"
  ) {
    return { action: "request_decision", attempt_number: prior_attempts + 1, max_attempts: 1 };
  }
  if (options.scope_failure_kind === "provider_overreach") {
    const max_attempts = 1;
    const attempt_number = prior_attempts + 1;
    return prior_attempts >= max_attempts
      ? { action: "request_decision", attempt_number, max_attempts }
      : { action: "retry_with_evidence", attempt_number, max_attempts };
  }
}
```

Keep the existing `diff_scope_failed` default as a fallback for older events and tests.

- [ ] **Step 4: Verify recovery tests**

Run:

```bash
bun test packages/orchestrator/tests/recoveryExecutor.test.ts
```

Expected: PASS.

### Task 4: Runtime Wiring and Operator Evidence

```yaml waygent-task
id: task_4_runtime_wiring_and_operator_evidence
title: Runtime wiring and operator evidence
dependencies:
  - task_1_generated_output_detector
  - task_2_diff_scope_classification
  - task_3_structural_recovery_policy
file_claims:
  - path: packages/orchestrator/src/taskExecutor.ts
    mode: owned
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
  - path: packages/lens-projectors/src/operatorDecision.ts
    mode: owned
  - path: packages/orchestrator/tests/orchestratorRunV2.test.ts
    mode: owned
  - path: packages/lens-projectors/tests/operatorDecision.test.ts
    mode: owned
risk: high
verify:
  - bun test packages/orchestrator/tests/orchestratorRunV2.test.ts
  - bun test packages/lens-projectors/tests/operatorDecision.test.ts
```

**Files:**
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `packages/lens-projectors/src/operatorDecision.ts`
- Modify: `packages/orchestrator/tests/orchestratorRunV2.test.ts`
- Modify: `packages/lens-projectors/tests/operatorDecision.test.ts`

- [ ] **Step 1: Add orchestrator regression test**

Add a test to `packages/orchestrator/tests/orchestratorRunV2.test.ts` near existing diff scope tests:

```ts
test("blocks generated fixture claim gaps without repeated provider retries", async () => {
  const result = await runWaygent({
    root: tempRoot(),
    workspace: fixtureWorkspace("readmates-zod-fixtures"),
    plan: [
      "# Fixture Claim Gap",
      "",
      "```yaml waygent-task",
      "id: task_contracts",
      "title: Contract sweep",
      "dependencies: []",
      "file_claims:",
      "  - path: front/scripts/export-zod-fixtures.ts",
      "    mode: owned",
      "risk: high",
      "verify:",
      "  - pnpm --dir front zod:export-fixtures",
      "  - git diff --exit-code front/tests/unit/__fixtures__/zod-schemas/",
      "```"
    ].join("\n"),
    profile: { provider: "fake", execution_mode: "multi-agent" },
    plan_preflight: "deterministic"
  });

  expect(result.status).toBe("blocked");
  const events = result.events ?? [];
  expect(events.some((event) => event.event_type === "runway.recovery_scheduled")).toBe(false);
  expect(events.some((event) => event.event_type === "runway.recovery_decision_required")).toBe(true);
  expect(JSON.stringify(events)).toContain("front/tests/unit/__fixtures__/zod-schemas/*.json");
});
```

If helpers such as `tempRoot()` or `fixtureWorkspace()` differ in the current file, use the existing local helper names instead of adding new infrastructure.

- [ ] **Step 2: Wire generated output context into task execution**

Modify `packages/orchestrator/src/taskExecutor.ts` imports:

```ts
import { detectGeneratedOutputs } from "./generatedOutputs";
```

Before `validateDiffScope(...)`, compute expected outputs:

```ts
const generatedOutputDetection = detectGeneratedOutputs({
  task_id: input.task.id,
  plan_text: input.plan_excerpt ?? input.task.title,
  verification_commands: input.task.verification_commands
});
```

Pass the outputs:

```ts
const scopeValidation = validateDiffScope({
  actual_changed_files: listActualChangedFiles(taskWorktree.path),
  claimed_changed_files: worker.changed_files,
  allowed_write_globs: writableClaimPaths(input.task),
  forbidden_write_globs: [".git/**", "node_modules/**"],
  expected_generated_outputs: generatedOutputDetection.expected_outputs
});
```

Add fields to the `runway.diff_scope_result` payload:

```ts
scope_failure_kind: scopeValidation.scope_failure_kind,
recommended_scope_amendments: scopeValidation.recommended_scope_amendments
```

- [ ] **Step 3: Pass scope failure kind to recovery**

In `packages/orchestrator/src/orchestrator.ts`, where `recordTaskRecovery(...)` is called for task failures, extract the most recent `runway.diff_scope_result` payload for the task. Pass the kind into recovery:

```ts
const scopeFailureKind = latestDiffScopeFailureKind(context.state, taskId);
recordTaskRecovery(context, {
  task_id: taskId,
  failure_class: failureClass,
  prior_summary,
  evidence_refs,
  scope_failure_kind: scopeFailureKind
});
```

Update `recordTaskRecovery` input type:

```ts
input: {
  task_id: string;
  failure_class: FailureClass;
  prior_summary: string;
  evidence_refs: string[];
  scope_failure_kind?: ScopeFailureKind;
}
```

Thread that value into `appendSchedulerRecovery` or `nextRecoveryAction` depending on the current local call boundary.

- [ ] **Step 4: Add operator projection test**

Add to `packages/lens-projectors/tests/operatorDecision.test.ts`:

```ts
test("projects generated artifact claim gap amendments", () => {
  const projection = projectOperatorDecision(runStateWithDiffScopeFailure({
    task_id: "task_contracts",
    scope_failure_kind: "generated_artifact_unclaimed",
    recommended_scope_amendments: [
      {
        path: "front/tests/unit/__fixtures__/zod-schemas/current-session.json",
        mode: "owned",
        reason: "generated artifact is outside task writable claims",
        evidence_refs: ["command:pnpm --dir front zod:export-fixtures"]
      }
    ]
  }));

  expect(projection.primary_blocker?.code).toBe("diff_scope_failed");
  expect(JSON.stringify(projection)).toContain("front/tests/unit/__fixtures__/zod-schemas/current-session.json");
  expect(projection.blocked_actions.some((action) => action.id === "apply_run")).toBe(true);
});
```

If `runStateWithDiffScopeFailure` is not present, build a minimal state fixture using the existing helpers in that test file.

- [ ] **Step 5: Implement projection fields**

Modify `packages/lens-projectors/src/operatorDecision.ts` so diff-scope blockers include:

```ts
summary: "Task generated files outside its writable claims. Add the recommended claims and rerun.",
evidence_refs: [
  ...existingRefs,
  ...recommended_scope_amendments.map((claim) => `missing-claim:${claim.path}`)
]
```

Keep the existing `apply_run` blocked action.

- [ ] **Step 6: Verify runtime and projection tests**

Run:

```bash
bun test packages/orchestrator/tests/orchestratorRunV2.test.ts
bun test packages/lens-projectors/tests/operatorDecision.test.ts
```

Expected: PASS.

### Task 5: Regression Scenario and Docs

```yaml waygent-task
id: task_5_regression_scenario_and_docs
title: Regression scenario and docs
dependencies:
  - task_4_runtime_wiring_and_operator_evidence
file_claims:
  - path: packages/testkit/src/waygentScenarioHarness.ts
    mode: owned
  - path: tests/waygent-scenarios/generated-fixture-claim-gap.json
    mode: owned
  - path: docs/operations/plan-authoring.md
    mode: owned
  - path: docs/operations/recovery.md
    mode: owned
risk: medium
verify:
  - bun run waygent:scenarios
  - git diff --check
```

**Files:**
- Modify: `packages/testkit/src/waygentScenarioHarness.ts`
- Create: `tests/waygent-scenarios/generated-fixture-claim-gap.json`
- Modify: `docs/operations/plan-authoring.md`
- Modify: `docs/operations/recovery.md`

- [ ] **Step 1: Add scenario fixture**

Create `tests/waygent-scenarios/generated-fixture-claim-gap.json`:

```json
{
  "id": "generated-fixture-claim-gap",
  "title": "Generated fixture claim gap blocks without repeated retry",
  "plan": "# Generated Fixture Claim Gap\n\n```yaml waygent-task\nid: task_contracts\ntitle: Contract confidence sweep\ndependencies: []\nfile_claims:\n  - path: front/scripts/export-zod-fixtures.ts\n    mode: owned\nrisk: high\nverify:\n  - pnpm --dir front zod:export-fixtures\n  - git diff --exit-code front/tests/unit/__fixtures__/zod-schemas/\n```",
  "provider": "fake",
  "expected": {
    "status": "blocked",
    "trust_status": "failed",
    "event_types": [
      "runway.recovery_decision_required",
      "lens.trust_report_updated"
    ],
    "absent_event_types": [
      "runway.recovery_scheduled"
    ],
    "contains": [
      "generated_artifact_unclaimed",
      "front/tests/unit/__fixtures__/zod-schemas/*.json"
    ]
  }
}
```

If current scenario fixtures use a different schema, adapt only the field names while preserving the assertions.

- [ ] **Step 2: Extend scenario harness**

Modify `packages/testkit/src/waygentScenarioHarness.ts` to support `absent_event_types` and `contains` assertions if missing:

```ts
for (const eventType of scenario.expected.absent_event_types ?? []) {
  assert(!events.some((event) => event.event_type === eventType), `unexpected event_type ${eventType}`);
}

const serialized = JSON.stringify({ state, events });
for (const needle of scenario.expected.contains ?? []) {
  assert(serialized.includes(needle), `expected scenario output to contain ${needle}`);
}
```

- [ ] **Step 3: Document plan-authoring rule**

Add to `docs/operations/plan-authoring.md`:

````md
### Generated Artifacts Must Be Claimed

If a task runs a generator, exporter, codegen command, fixture exporter, or
snapshot update, the task file claims must include the generated output paths.

Example:

```yaml
verify:
  - pnpm --dir front zod:export-fixtures
file_claims:
  - path: front/scripts/export-zod-fixtures.ts
    mode: owned
  - path: front/tests/unit/__fixtures__/zod-schemas/*.json
    mode: owned
```

Waygent may detect known generated outputs and block before dispatch with a
scope-gap report. It will not widen task claims automatically.
````

- [ ] **Step 4: Document recovery behavior**

Add to `docs/operations/recovery.md`:

```md
### Structural Scope Failures

`diff_scope_failed` is split into retryable and non-retryable kinds.

- `generated_artifact_unclaimed`: a task produced expected generated files that
  are outside `allowed_write_globs`. Waygent requests an operator decision and
  lists missing claims.
- `forbidden_write`: a task touched forbidden paths such as `.git/**` or
  `node_modules/**`. Waygent requests an operator decision and never retries.
- `provider_claim_gap`: actual changed files were not reported by the provider.
  Waygent requests a decision because the worker evidence is inconsistent.
- `provider_overreach`: a task changed unrelated files. Waygent may retry once
  with evidence, then requests a decision.

No structural scope failure can produce a checkpoint or release dependent tasks.
```

- [ ] **Step 5: Verify scenarios and docs**

Run:

```bash
bun run waygent:scenarios
git diff --check
```

Expected: PASS.

## Traceability Matrix

| Spec requirement | Tasks | Verification |
| --- | --- | --- |
| R1 Scope Failure Kinds | Task 2, Task 4 | `bun test packages/orchestrator/tests/diffScope.test.ts` |
| R2 Structural Failures Do Not Retry | Task 3, Task 5 | `bun test packages/orchestrator/tests/recoveryExecutor.test.ts`, `bun run waygent:scenarios` |
| R3 Generated Output Detector | Task 1 | `bun test packages/orchestrator/tests/generatedOutputs.test.ts` |
| R4 Pre-dispatch Scope Gap Report | Task 4 | `bun test packages/orchestrator/tests/orchestratorRunV2.test.ts` |
| R5 Scope Amendment Decision | Task 4 | `bun test packages/lens-projectors/tests/operatorDecision.test.ts` |
| R6 Strict Safe-wave Behavior | Task 4 | `bun test packages/orchestrator/tests/orchestratorRunV2.test.ts` |
| R7 Regression Fixture | Task 5 | `bun run waygent:scenarios` |

## Verification Plan

Targeted:

```bash
bun test packages/orchestrator/tests/generatedOutputs.test.ts
bun test packages/orchestrator/tests/diffScope.test.ts
bun test packages/orchestrator/tests/recoveryExecutor.test.ts
bun test packages/orchestrator/tests/orchestratorRunV2.test.ts
bun test packages/lens-projectors/tests/operatorDecision.test.ts
```

Full relevant gates:

```bash
bun run check
bun run waygent:scenarios
git diff --check
```

Manual CLI smoke after implementation:

```bash
waygent run --plan tests/fixtures/waygent-lab/generated-fixture-claim-gap.md --provider fake --plan-preflight deterministic
waygent explain --last
waygent inspect --last --json
```

Expected smoke result:

- `waygent explain` lists `generated_artifact_unclaimed`.
- It lists missing fixture claims.
- It does not report an apply-ready checkpoint.
- Dependent tasks remain withheld when a dependency checkpoint is missing.

## Rollback Plan

If the change causes false-positive scope blocks:

1. Revert `packages/orchestrator/src/generatedOutputs.ts` usage in `orchestrator.ts` and `taskExecutor.ts`.
2. Keep additive `scope_failure_kind` fields in event payloads if already released, because old consumers can ignore them.
3. Restore `diff_scope_failed` fallback behavior only for unknown scope kinds.
4. Re-run:

```bash
bun run check
bun run waygent:scenarios
git diff --check
```

## Risks

- The initial detector may miss generators outside Zod fixtures. This is acceptable because post-verification diff classification still catches the failure.
- The initial detector may block a valid task if a project intentionally checks fixture diffs read-only. This is mitigated by requiring explicit generator/path signals.
- Existing tests may assume `diff_scope_failed` retries twice. Update those expectations only where the failure is structural.
- Scenario harness schemas may differ from the proposed fixture. Adapt the fixture shape to the current harness instead of weakening the assertion.

## Done When

- Generated fixture claim gaps are blocked before repeated provider retries.
- `runway.diff_scope_result` includes `scope_failure_kind` and recommended claims.
- `waygent explain` tells the operator which claims to add.
- No checkpoint or apply can occur for an unclaimed generated artifact.
- `bun run check`, `bun run waygent:scenarios`, and `git diff --check` pass.
