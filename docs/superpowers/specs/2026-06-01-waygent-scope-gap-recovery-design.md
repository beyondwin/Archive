# Waygent Scope Gap Recovery Design

- **Date**: 2026-06-01
- **Type**: Superpowers design spec
- **Status**: Drafted for implementation planning
- **Scope**: Waygent plan intent compilation, generated output claim detection, diff scope failure classification, recovery policy, and operator decision evidence.

## Overview

Waygent currently enforces a strict runtime boundary: a task may only create a checkpoint when actual changed files are inside that task's `allowed_write_globs`, and downstream tasks may only run after upstream checkpoints exist. That safety boundary is correct.

The defect is upstream of that boundary. A plan can require generated artifacts, such as Zod fixture exports, while the normalized task file claims omit the generated output paths. The provider then makes the correct files, verification can pass, but checkpoint creation fails with `diff_scope_failed`. The recovery policy treats that failure as retryable provider work, so Waygent repeats the same task until recovery is exhausted. This is a runtime product defect because the failure is structural: the task's authority is incomplete.

This design keeps checkpoint and apply strictness intact. It adds a deterministic scope-gap layer before and after provider execution so Waygent can distinguish provider mistakes from plan authority gaps.

## Goals

1. Detect generated output claim gaps before provider dispatch when possible.
2. Classify diff scope failures into actionable kinds instead of one generic `diff_scope_failed`.
3. Stop retrying structural scope failures that cannot be fixed by another provider attempt.
4. Emit an operator decision packet that lists the exact missing claims and why they are needed.
5. Preserve current safety behavior: no checkpoint, downstream dispatch, or apply without bounded scope evidence.
6. Add deterministic regression coverage for the ReadMates fixture-export failure shape.

## Non-goals

- Do not loosen `allowed_write_globs` automatically during a run.
- Do not apply uncheckpointed provider diffs.
- Do not let providers request their own write-scope expansion.
- Do not route active Waygent execution through KWS executor skills.
- Do not replace existing safe-wave dependency scheduling.
- Do not build a full language parser for every package manager script in this change.

## Requirements

### R1 - Scope Failure Kinds

`runway.diff_scope_result` must include a stable `scope_failure_kind` when scope validation fails.

Acceptance criteria:

- Forbidden paths classify as `forbidden_write`.
- Changed files outside allowed claims but matching generated-output evidence classify as `generated_artifact_unclaimed`.
- Changed files outside allowed claims without generated-output evidence classify as `provider_overreach`.
- Changed files missing from provider-reported `changed_files` classify as `provider_claim_gap`.

### R2 - Structural Scope Failures Do Not Retry

Recovery must not schedule another provider attempt for structural scope gaps.

Acceptance criteria:

- `generated_artifact_unclaimed` produces `runway.recovery_decision_required` on the first occurrence.
- Repeated identical violating files produce `runway.recovery_decision_required` even if the first occurrence was classified as ambiguous.
- `forbidden_write` produces a hard operator decision and never retries.
- Accidental `provider_overreach` may retry at most once with evidence.

### R3 - Generated Output Detector

Waygent must detect common generated output intent from deterministic plan and command signals.

Initial detector signals:

- Verification or plan command contains `zod:export-fixtures`.
- Verification or plan command contains `front/tests/unit/__fixtures__/zod-schemas`.
- Plan text contains `export fixtures`, `zod fixtures`, `schema fixtures`, or `generated fixtures`.

Initial output mapping:

- `zod:export-fixtures` maps to `front/tests/unit/__fixtures__/zod-schemas/*.json`.

Acceptance criteria:

- The detector returns expected output globs with evidence refs to commands or plan excerpts.
- The detector does not mark arbitrary unclaimed source files as generated outputs.
- The detector is additive and project-safe: unknown commands produce no expected outputs.

### R4 - Pre-dispatch Scope Gap Report

Before dispatch, Waygent must compare expected generated outputs with task file claims.

Acceptance criteria:

- If expected outputs are not covered by writable claims, the task is blocked before provider dispatch when deterministic preflight is enabled.
- The run records a `scope_gap_report` artifact with task id, missing claim globs, source signals, and recommended amendments.
- `waygent explain` surfaces the missing claims as the primary next action.

### R5 - Post-verification Scope Amendment Decision

When a provider produces unclaimed generated artifacts that were not caught before dispatch, Waygent must stop at a decision packet instead of retrying the task.

Acceptance criteria:

- `runway.diff_scope_result` includes `violating_files`, `allowed_write_globs`, `provider_claimed_changed_files`, and `recommended_scope_amendments`.
- The operator decision projection includes an allowed action to inspect evidence, and blocks apply.
- The decision text lists exact file paths or globs to add to the task claim.

### R6 - Safe-wave Behavior Remains Strict

Downstream tasks must remain withheld until upstream checkpoint creation succeeds.

Acceptance criteria:

- A task blocked by `generated_artifact_unclaimed` has zero checkpoints.
- Dependent tasks remain `pending` with a checkpoint barrier.
- Apply readiness remains `not_ready` or blocked with no combined patch.

### R7 - Regression Fixture

The ReadMates failure shape must become a deterministic Waygent scenario.

Acceptance criteria:

- A fixture run with `zod:export-fixtures` and missing fixture claims blocks before dispatch or immediately after first diff scope check.
- It emits no repeated provider retry for the same violating files.
- It includes missing claims for:
  - `front/tests/unit/__fixtures__/zod-schemas/admin-analytics-overview.json`
  - `front/tests/unit/__fixtures__/zod-schemas/current-session.json`

## User Experience

When Waygent detects this problem, the operator should see a direct explanation instead of an apparent provider failure.

Example `waygent explain` summary:

```text
task_1_contract_confidence_sweep is blocked by generated_artifact_unclaimed.

The task generated Zod fixture files required by zod:export-fixtures, but those
files are outside the task's writable claims.

Add these file claims to the task, then rerun:
- front/tests/unit/__fixtures__/zod-schemas/admin-analytics-overview.json
- front/tests/unit/__fixtures__/zod-schemas/current-session.json
```

The runtime must keep `apply` blocked until the operator approves a plan or scope amendment and Waygent reruns with a valid checkpoint.

## Architecture

### Components

- `packages/orchestrator/src/diffScope.ts`
  - Classifies scope validation failures and carries recommended amendments.
- `packages/orchestrator/src/generatedOutputs.ts`
  - New pure detector for generated output signals and expected output globs.
- `packages/orchestrator/src/taskExecutor.ts`
  - Emits richer diff scope events and avoids checkpoint creation when classification fails.
- `packages/orchestrator/src/recoveryExecutor.ts`
  - Chooses retry or decision based on scope failure kind.
- `packages/orchestrator/src/orchestrator.ts`
  - Runs deterministic scope-gap preflight when normalized tasks are known.
- `packages/lens-projectors/src/operatorDecision.ts`
  - Projects missing claims and next actions into `waygent explain`, API, and console consumers.
- `packages/testkit/src/waygentScenarioHarness.ts`
  - Adds a deterministic scenario for generated fixture claim gaps.

### Control Flow

```text
plan/spec
  -> normalize tasks
  -> detect expected generated outputs
  -> compare expected outputs against file claims
  -> block with scope_gap_report when deterministic gap exists
  -> otherwise dispatch provider
  -> verify
  -> validate actual diff scope
  -> classify scope failure
  -> request decision for structural scope gaps
  -> create checkpoint only when scope is valid
```

## Data

### New Event Payload Fields

`runway.diff_scope_result.payload` gains:

```ts
scope_failure_kind:
  | "generated_artifact_unclaimed"
  | "provider_overreach"
  | "provider_claim_gap"
  | "forbidden_write";
recommended_scope_amendments: Array<{
  path: string;
  mode: "owned";
  reason: string;
  evidence_refs: string[];
}>;
```

### New Artifact

`waygent.scope_gap_report.v1`:

```ts
interface ScopeGapReport {
  schema: "waygent.scope_gap_report.v1";
  run_id: string;
  task_id: string;
  status: "blocked";
  expected_outputs: Array<{
    path_glob: string;
    reason: string;
    evidence_refs: string[];
  }>;
  missing_claims: Array<{
    path: string;
    mode: "owned";
    reason: string;
  }>;
  existing_allowed_write_globs: string[];
}
```

This artifact is runtime evidence only. It does not mutate the plan or widen task permissions by itself.

## Traceability Matrix

| Requirement | Implementation | Verification |
| --- | --- | --- |
| R1 | `diffScope.ts` classification and tests | `bun test packages/orchestrator/tests/diffScope.test.ts` |
| R2 | `recoveryExecutor.ts` structural policy | `bun test packages/orchestrator/tests/recoveryExecutor.test.ts` |
| R3 | `generatedOutputs.ts` detector | `bun test packages/orchestrator/tests/generatedOutputs.test.ts` |
| R4 | orchestrator pre-dispatch report | `bun test packages/orchestrator/tests/orchestratorRunV2.test.ts` |
| R5 | event payload and operator projection | `bun test packages/lens-projectors/tests/operatorDecision.test.ts` |
| R6 | safe-wave dependency tests | `bun test packages/orchestrator/tests/orchestratorRunV2.test.ts` |
| R7 | scenario harness fixture | `bun run waygent:scenarios` |

## Verification Plan

Run targeted checks first:

```bash
bun test packages/orchestrator/tests/diffScope.test.ts
bun test packages/orchestrator/tests/recoveryExecutor.test.ts
bun test packages/orchestrator/tests/generatedOutputs.test.ts
bun test packages/orchestrator/tests/orchestratorRunV2.test.ts
bun test packages/lens-projectors/tests/operatorDecision.test.ts
```

Then run the product-level checks:

```bash
bun run check
bun run waygent:scenarios
git diff --check
```

Manual smoke:

```bash
waygent inspect --run <fixture-run> --json
waygent explain --run <fixture-run>
```

Confirm the explanation lists missing generated fixture claims and no repeated provider retry is scheduled.

## Risks

- A detector that is too broad could block valid tasks. Mitigation: start with explicit known commands and path signals only.
- A detector that is too narrow still allows post-verification scope gaps. Mitigation: post-verification classification remains mandatory.
- Scope amendment UX could be mistaken for automatic permission widening. Mitigation: reports only recommend claims; they do not mutate runtime authority.
- Existing tests may assert generic `diff_scope_failed` behavior. Mitigation: keep `failure_class` stable and add `scope_failure_kind` as additive metadata.

## Open Questions

- Should `waygent repair` eventually support an explicit `--add-claim` workflow, or should claim amendment remain a plan-edit-only operation?
- Should deterministic preflight become the default for all `waygent run` invocations, or start as a profile-controlled gate?
- Should generated output mappings live in code, project config, or both?
