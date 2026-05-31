# Waygent Recovery-to-Review Loop Design

- **Date**: 2026-06-01
- **Type**: Brainstorming-approved design spec
- **Status**: Approved design, pending implementation plan
- **Scope**: Failure evidence classification, salvage artifacts, repair-first
  recovery, provider-backed review readiness, Lens/operator projections, and
  deterministic fixture coverage for recovered Waygent runs.
- **Next artifact**: implementation plan via `superpowers:writing-plans`

## 1. Goal

Waygent should recover useful work from failed runs before paying for a full
retry, and recovered work should not become apply-ready until review and
verification evidence prove it is safe.

The target lifecycle is:

```text
provider failure / verification failure / malformed output / adapter crash
  -> classify recoverable evidence
  -> record salvage candidate when patch or worker evidence exists
  -> dispatch focused repair when appropriate
  -> run spec and quality review when recovery made review required
  -> rerun verification
  -> create checkpoint and completion audit evidence
  -> update apply readiness and operator explanation
```

The work stays inside the active Waygent product runtime. It must not route
active execution through KWS executor skills, recreate legacy Python AgentLens,
or let provider output bypass Waygent-owned verification, review, checkpoint,
reconciliation, and apply-readiness gates.

## 2. Problem

Waygent already records provider attempts, verification, checkpoints, review
evidence, budget signals, stale-run status, and operator projections. The
remaining gap is the connection between those pieces when a run fails but still
contains useful evidence.

Common failure shapes are:

- a worker produced a patch but verification failed;
- provider output was malformed but the worktree contains a useful diff;
- a provider process crashed or timed out after making partial changes;
- recovery made review mandatory but the operator sees an apply-readiness
  blocker instead of a direct recovery path;
- old failure evidence remains visible but is not clearly separated from the
  current blocker.

The runtime should distinguish "no useful evidence" from "recoverable evidence
needs repair, review, and verification." That distinction is what allows
Waygent to save cost while keeping the apply boundary strict.

## 3. Design Principles

### 3.1 Salvage is not success

A salvaged patch or recovered worker result is only candidate evidence. It may
start repair, review, or verification, but it must not create an apply-ready
checkpoint by itself.

### 3.2 Repair before full retry

When the runtime already has a patch and a bounded failure reason, the default
next step is focused repair. Full implementer retry is reserved for missing,
unsafe, or exhausted repair evidence.

### 3.3 Review closes recovered work

Recovered tasks need review evidence when recovery, high risk, broad claims,
method evidence policy, malformed output, or adapter crashes made review
required. A recovered task without required review should block as
`review_evidence_missing`, not as a generic apply-readiness failure.

### 3.4 Operator projections are shared

`waygent explain`, API detail, and console models should read the same durable
projection for active blocker, recovered evidence, next action, and why apply
is not ready.

### 3.5 Fake-provider tests come first

The feature must be proven with deterministic fake-provider and synthetic run
fixtures before opt-in live provider review paths are used.

## 4. Architecture

### 4.1 Failure Evidence Classifier

Add a small classifier in `packages/orchestrator` that reads:

- `ProviderAttempt`
- `WorkerResult`
- stdout and stderr artifact refs
- captured patch refs
- task verification records
- file-claim and diff-scope status
- current repair and budget counters

The classifier returns a bounded decision:

```ts
type FailureEvidenceDecision =
  | {
      kind: "recoverable_patch";
      task_id: string;
      failure_class: string;
      patch_ref: string;
      changed_files: string[];
      evidence_refs: string[];
      recommended_action: "dispatch_repair" | "salvage_then_review";
    }
  | {
      kind: "recoverable_worker_result";
      task_id: string;
      failure_class: string;
      worker_result_ref: string;
      evidence_refs: string[];
      recommended_action: "dispatch_repair";
    }
  | {
      kind: "needs_operator_decision";
      task_id: string;
      failure_class: string;
      reason: string;
      evidence_refs: string[];
    }
  | {
      kind: "terminal_unrecoverable";
      task_id: string;
      failure_class: string;
      reason: string;
      evidence_refs: string[];
    };
```

Initial rules:

- `verification_failed` with completed worker result and patch evidence returns
  `recoverable_patch` with `dispatch_repair`.
- `malformed_result`, `adapter_crashed`, or `timeout` with a captured worktree
  diff returns `recoverable_patch` with `salvage_then_review`.
- environment, dependency, command-not-found, dirty-checkout, file-claim
  conflict, and budget exhaustion return `needs_operator_decision`.
- repeated review failure beyond the repair budget returns
  `terminal_unrecoverable`.

### 4.2 Salvage Artifact Writer

When a failed attempt contains a safe candidate patch, Waygent writes or updates
a `waygent.salvage_result.v1` artifact:

```ts
interface SalvageResult {
  schema: "waygent.salvage_result.v1";
  task_id: string;
  attempt_id: string;
  status: "salvaged_patch" | "no_patch" | "unsafe_patch";
  patch_ref: string | null;
  changed_files: string[];
  reason: string | null;
  evidence_refs: string[];
}
```

The artifact is linked from task recovery state and emitted through a
`runway.patch_salvaged` event. If diff-scope or file-claim checks cannot prove
the patch is bounded, the salvage result must be `unsafe_patch` and the run must
ask for an operator decision.

### 4.3 Repair-to-Review Scheduler

The scheduler extends the existing repair-first path:

```text
failed_with_patch
  -> salvage_recorded
  -> repair_pending
  -> repair_running
  -> repair_failed | repair_completed
  -> review_pending
  -> review_failed | review_passed
  -> verify_pending
  -> verified
  -> checkpoint_ready
```

Rules:

- A repair packet includes the prior diff, failure evidence, verification
  diagnostics, and any review issues.
- A successful repair invalidates prior failed review evidence for that task and
  schedules review again when policy requires it.
- Review failure records `review_failed` or `review_changes_requested`; it must
  not be collapsed into `verification_failed`.
- Fake-provider tests may use deterministic review artifacts. Live provider
  review should be opt-in or profile-controlled until stable.

### 4.4 Provider-backed Review Readiness

Provider-backed review is a narrow extension, not a new orchestrator path.

The review runner builds bounded review packets for:

- `spec_reviewer`: checks task/spec compliance and missing acceptance evidence.
- `quality_reviewer`: checks maintainability, local patterns, tests, and risky
  side effects.

Provider-backed review output is normalized into `waygent.task_review.v1`.
Malformed review output becomes review failure evidence and may dispatch repair
only when a patch and review issue list exist. Manual or deterministic review
artifacts remain valid for tests and offline workflows.

### 4.5 Lens and Operator Projection

Lens projections should expose:

- `active_blocker`: the current blocker that prevents resume or apply.
- `recoverable_evidence`: salvage or repair candidates with artifact refs.
- `recovered_failures`: older failures resolved by later repair, review, and
  verification evidence.
- `recommended_action`: one of inspect, repair, review, verify, resume, apply,
  or request operator input.
- `why_not_apply_ready`: exact missing contract, such as review evidence,
  checkpoint evidence, combined apply evidence, verification, reconciliation, or
  clean checkout.

`waygent explain` should prefer this projection instead of recomputing from
events. API and console can initially surface the new fields without a major UI
redesign.

## 5. Error Handling

Automatic recovery candidates:

- `verification_failed` plus patch evidence: dispatch repair.
- `malformed_result` plus safe diff: record salvage and route to review/repair.
- `adapter_crashed` plus safe diff: record salvage and route to review/repair.
- `timeout` plus safe partial patch: record salvage and route to review/repair.

Operator decision cases:

- no patch or worker evidence exists;
- diff scope is unsafe or does not match file claims;
- verification command is invalid or mutates source;
- dependency, environment, or command availability is blocked;
- file-claim conflict or dirty source checkout prevents safe action;
- review repeats the same failure beyond the repair budget;
- budget policy pauses the run.

The runtime must record enough evidence for each stop: failure class, attempted
automatic action, why it stopped, safe commands, and bounded artifact refs.

## 6. Testing Strategy

### Unit tests

Add focused tests for the classifier:

- verification failure with patch evidence selects repair;
- malformed provider output with safe diff selects salvage then review;
- adapter crash without diff asks for operator decision;
- unsafe diff-scope blocks salvage;
- exhausted repair budget becomes terminal or decision-required.

### Orchestrator integration tests

Cover fake-provider flows:

- failed-with-patch becomes salvage/repair evidence instead of full retry;
- repair success schedules review when recovery made review required;
- review pass plus verification pass creates checkpoint-ready evidence;
- review failure remains a review blocker.

### Lens projection tests

Assert:

- stale failures move to `recovered_failures` after later success;
- salvage candidates appear in `recoverable_evidence`;
- missing recovered-task review blocks as `review_evidence_missing`;
- explain/API/console model agree on the same primary blocker.

### Scenario and fixture lab

Add representative fixtures under `tests/waygent-scenarios/` or
`tests/fixtures/waygent-lab/` for:

- `adapter-crash-salvaged-patch`
- `malformed-output-salvaged-patch`
- `verification-failed-repair-reviewed`
- `review-failed-repair-budget-exhausted`

Default verification for the implementation plan should include:

```bash
bun test packages/orchestrator/tests packages/lens-projectors/tests
bun run waygent:fixture-lab
bun run waygent:scenarios
bun run waygent:dogfood
git diff --check
```

Add `bun run --cwd apps/console build` if the console UI or model surface
changes beyond additive model fields.

## 7. Rollout

### Phase 1: Classification and Projection

Add the classifier and read-only projections first. This makes explain output
more accurate without changing scheduling behavior.

Acceptance evidence:

- classifier unit tests pass;
- Lens projection tests show recovered and active failures separately;
- `waygent explain` reports the precise next action from state.

### Phase 2: Salvage and Repair Scheduling

Record salvage artifacts and route safe patch failures into repair before full
retry.

Acceptance evidence:

- fake-provider integration tests record `waygent.salvage_result.v1`;
- unsafe patches ask for operator decision;
- repair budget prevents unbounded loops.

### Phase 3: Provider-backed Review Readiness

Connect review packets to provider-backed reviewer roles behind opt-in profile
or explicit review mode.

Acceptance evidence:

- deterministic review path remains stable for fake-provider gates;
- provider-backed review normalizes to `waygent.task_review.v1`;
- malformed review output is a review blocker, not a verification blocker.

## 8. Non-Goals

- Do not make salvaged patches apply-ready without review and verification.
- Do not implement a large console redesign in this slice.
- Do not add cloud services or hosted CI.
- Do not bypass completion audit, checkpoint manifests, dry-run evidence,
  reconciliation, or clean-checkout validation.
- Do not route active Waygent work through historical AgentRunway or KWS
  executor paths.
- Do not make live provider review part of the default offline gate.

## 9. Implementation Defaults

The implementation plan should use these defaults unless current code makes a
specific default impossible:

- Put the classifier in a new `packages/orchestrator/src/failureEvidence.ts`
  module so task recovery policy and evidence classification stay separate.
- Reuse the existing `waygent.salvage_result.v1` contract when it already
  covers the fields in this spec; add schema fields only for gaps found by
  contract tests.
- Control provider-backed review through existing `review_mode: "strict"` for
  this slice. Do not introduce a second review opt-in flag until strict mode
  proves too broad.
- Make `malformed-output-salvaged-patch` and
  `verification-failed-repair-reviewed` the first required scenario fixtures.
  Add adapter-crash and review-budget fixtures after those two pass.
