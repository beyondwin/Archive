# Waygent Operational Trust Loop Design

## Goal

Waygent has crossed the first apply-readiness threshold: completed fake-provider
runs can produce manifest-backed checkpoints, materialize a combined apply
patch, and apply only after completion audit passes. The next maturity slice is
to make that trust loop consistent across run preflight, live provider
execution, evidence reconciliation, API, console, and dogfood gates.

The operator-facing promise is:

1. `waygent run` never mutates the source checkout.
2. `waygent run` records enough evidence to explain why a run is completed,
   blocked, or unsafe to apply.
3. Codex and Claude providers remain bounded workers behind task packets.
4. `waygent apply` mutates the source checkout only from verified,
   materialized, digest-checked checkpoints.
5. API and console show the same apply-readiness truth that `resume` and
   `apply` enforce.

## Source Audit Basis

This design is based on the current source state at commit `5887d84`:

- `packages/orchestrator/src/orchestrator.ts`
  - `runWaygent()` removes an existing run root for the same `run_id`.
  - Task worktrees are created per task through `planWorktree()` plus a local
    `prepareTaskWorktree()` helper.
  - Task packets, provider attempts, verification records, checkpoint
    manifests, checkpoint dry runs, combined apply evidence, and completion
    audit are already produced for the happy path.
- `packages/orchestrator/src/runCommands.ts`
  - `resumeRun()` gates `apply_verified_checkpoint` through
    `hasApplyReadyCheckpoint()`.
  - `applyRun()` checks completion audit, checkpoint manifests, combined patch
    availability, digest, clean source checkout, patch dry-run, and post-apply
    verification.
- `packages/orchestrator/src/sourceCheckout.ts`
  - Source checkout dirty classification exists but is not yet connected to
    `runWaygent()` preflight.
- `packages/orchestrator/src/stateReconciliation.ts`
  - Reconciliation checks task packet artifacts and unit manifests, but not
    provider artifacts, verification artifacts, checkpoint manifests, combined
    patch evidence, or event/state drift.
- `packages/provider-adapters/src/processAdapters.ts`
  - Codex and Claude process adapters normalize direct JSON, JSONL, and fenced
    JSON into `runway.worker_result.v1`.
  - The normalized result currently wraps native provider evidence but does not
    preserve a provider-supplied top-level `failure_class`.
- `packages/lens-projectors/src/apply.ts`
  - Event-only apply projection marks verification success as `ready`, while
    the runtime now requires completion audit plus combined apply evidence.
- `apps/api/src/server.ts` and `apps/console/src/uiModel.ts`
  - Real run detail can expose v2 state evidence, but list summary and console
    apply affordance do not yet share one readiness contract.
- `tests/integration/waygent-live-provider-smoke.test.ts` and
  `packages/testkit/src/waygentScenarioHarness.ts`
  - Offline scenario and live-smoke coverage exist, but normalization is still
    mostly event-payload based and does not verify v2 completion audit as the
    source of truth.

Recent focused verification passed during the source audit:

```bash
bun test packages/orchestrator/tests/orchestratorApplyE2E.test.ts \
  packages/orchestrator/tests/orchestratorRunV2.test.ts \
  packages/orchestrator/tests/orchestrator.test.ts

bun test packages/provider-adapters/tests packages/lens-projectors/tests \
  apps/api/tests apps/console/src \
  packages/orchestrator/tests/runCommandsV2.test.ts \
  packages/orchestrator/tests/sourceCheckout.test.ts \
  packages/orchestrator/tests/stateReconciliation.test.ts
```

## Non-Goals

- Do not reintroduce KWS CPE/CME as active runtime dependencies.
- Do not add active `kws-cpe.*`, `kws-cme.*`, or `kws.orchestrator.*` event
  namespaces.
- Do not make AgentLens mutate Waygent state.
- Do not build remote execution, cloud queues, or multi-user SaaS behavior.
- Do not make live Codex or Claude smoke checks part of default local
  verification.
- Do not turn the console into an apply mutator in this slice. The console may
  show readiness and commands, but `waygent apply` remains the explicit mutation
  action.

## Design Principles

### One Readiness Contract

Apply readiness has one meaning:

- every verified task has at least one valid checkpoint manifest;
- checkpoint patch bytes exist and match recorded digest and byte length;
- each checkpoint dry-run passed against the source checkout state used for
  completion audit;
- combined apply evidence exists, points to a materialized patch, and passes
  digest and byte-length checks;
- state reconciliation has no unrepaired blockers.

`resumeRun()`, `applyRun()`, API summaries, API detail, Lens projections for
real runs, and console buttons must all derive from that contract.

### Source Checkout Is Protected Twice

`waygent run` protects source state before work starts. `waygent apply`
protects source state before mutation.

Run preflight classifies source checkout dirtiness against file claims:

- `clean`: proceed.
- `dirty_unrelated`: proceed, but record a preflight warning and include it in
  state and inspect output. The task worktree still starts from committed
  source state, so the warning must be visible.
- `dirty_related`: block automatic run dispatch and write a decision packet.
  A related dirty file means Waygent cannot know whether the provider should
  build on user edits or on `HEAD`.

Apply remains stricter: any dirty source checkout blocks mutation.

### Providers Are Bounded Workers

Provider output is evidence, never final truth. A live provider can implement,
review, or fix inside the isolated worktree, but Waygent decides verification,
checkpoint validity, completion, and apply readiness.

Provider adapters must preserve the provider's useful failure classification
without trusting provider success claims. If a provider returns
`status: failed` with `failure_class: verification_failed`, the normalized
`WorkerResult` must keep that failure class. If it returns `status: completed`,
Waygent must still run kernel verification and checkpoint sealing.

### Reconciliation Closes The Loop

Completion audit is necessary but not enough by itself. Reconciliation must
re-read the filesystem state after audit construction and block false
completion if artifacts are missing, corrupted, or inconsistent.

The reconciler is the final local consistency barrier before a run can stay
`completed`.

### Operator Surfaces Do Not Guess

The API and console should not infer apply readiness from a successful
verification event alone. Event-only projections are acceptable for legacy or
demo views, but real Waygent run views must prefer `waygent.run_state.v2`,
completion audit, and reconciliation evidence.

## Target Runtime Flow

### 1. Run Preflight

`runWaygent()` starts by resolving the plan and task graph, then classifying the
source checkout against all task file claims.

Preflight writes a `runway.preflight_result` event and a v2 state preflight
record before dispatch. If the checkout is `dirty_related`, the run status
becomes `blocked`, the current phase becomes `preflight`, and no provider is
dispatched. The recovery action is `clean_source_checkout`.

If the checkout is `dirty_unrelated`, the run proceeds, but the state keeps a
warning record. The warning must be visible from `inspect`, API detail, and the
console.

### 2. Run Identity And Evidence Preservation

`runWaygent()` must stop deleting existing run evidence by default. If the
target run root already contains `state.json` or `events.jsonl`, default
behavior is to block with `run_id_already_exists`.

Allowed future paths:

- generated run ids for normal CLI runs;
- explicit `--run <id>` for deterministic tests;
- explicit `--replace-run` or test-only helper for cases that intentionally
  reset evidence;
- `resume` for continuing a run.

This preserves AgentLens replayability and prevents a repeated command from
silently erasing the only evidence explaining a previous failure.

### 3. Worktree And Task Packet Boundary

The current task packet builder already records write globs, forbidden globs,
verification commands, dependency ids, and packet hash. The next step is to
turn the packet into an enforceable boundary:

- provider prompt includes the task packet path and an inline contract summary;
- provider cwd is always the task worktree;
- provider result `changed_files` is compared to actual worktree diff;
- actual changed files must be inside `allowed_write_globs`;
- writes under forbidden globs produce `diff_scope_failed`;
- dependency checkpoint refs are included in packet `checkpoint_inputs`;
- retry packets include previous failure evidence and recovery decision ids.

The local `prepareTaskWorktree()` helper can remain initially, but the
worktree manifest should be produced through `packages/kernel-client` so that
the TypeScript control plane and Rust kernel share one ownership model.

### 4. Provider Normalization

Codex and Claude adapters keep their current process boundary but add stricter
normalization:

- preserve provider-supplied `failure_class` when valid;
- preserve provider-supplied `status` without defaulting unknown values to
  success;
- keep raw stdout, stderr, event stream, and parsed worker result as artifacts;
- record missing executable, timeout, crash, malformed output, and blocked
  output as distinct provider attempt evidence;
- ensure `runway.provider_attempt.v1` references every provider artifact.

Provider success remains insufficient for task success. Waygent still runs
verification and checkpoint sealing.

### 5. Verification And Checkpoint Sealing

Verification remains external to the provider. The verification runner already
uses `kernel.execution_request.v1` and records bounded stdout/stderr digests.
The trust loop adds:

- verification artifact existence checks in reconciliation;
- changed-file evidence after verification;
- explicit failure mapping from verification result to task failure class;
- checkpoint creation only after verification success and write-scope
  validation.

Read-only tasks cannot create apply-ready checkpoints. If a plan contains only
read-only tasks, completion must be represented as inspection-only, not
apply-ready.

### 6. Completion Audit And Reconciliation

Completion audit records:

- required checks;
- verification evidence;
- review evidence when present;
- per-task checkpoint evidence;
- combined apply patch evidence;
- prompt-to-artifact checklist;
- residual risk.

Reconciliation then checks:

- `task_packet_path` exists and matches `task_packet_sha256`;
- each provider attempt artifact exists;
- each `worker_result_ref` exists when a worker result was expected;
- each verification `kernel_result_ref` exists;
- each verified task has a valid checkpoint manifest;
- each checkpoint patch exists and matches digest and byte length;
- each checkpoint dry-run evidence artifact exists;
- combined apply patch exists and matches digest and byte length;
- event journal exists and contains the expected terminal event family;
- v2 state status is consistent with completion audit and event outcomes.

Any missing or corrupted evidence writes a drift record and blocks the run.

### 7. Resume And Recovery Policy

`resumeRun()` remains conservative:

- completed and apply-ready: `inspect_run`, `apply_verified_checkpoint`;
- completed but evidence-drifted: `inspect_run`,
  `retry_checkpoint_generation`, `human_decision`;
- dirty source: `clean_source_checkout`;
- provider crash, timeout, malformed result: bounded retry, then switch
  provider or human decision;
- verification failure: rerun verification, then human decision;
- state drift or artifact missing: retry checkpoint generation only when the
  required worktree and provider artifacts still exist.

Resume must not recreate a result from chat context. It may only use durable
state, artifacts, and explicit operator input.

### 8. API And Console Truth Alignment

Real run API responses add a derived `apply_readiness` projection:

```json
{
  "status": "ready|not_ready|blocked|applied",
  "reason": "string|null",
  "checkpoint_refs": [],
  "combined_patch_ref": "string|null",
  "source": "run_state_v2|events"
}
```

For real runs, API list and detail both derive `apply_status` from this
projection. Event-only `projectApplyState()` remains available for demo or
legacy event replay, but it must not override v2 state.

The console uses this projection for:

- the apply status label;
- whether the apply command is enabled or disabled;
- the reason displayed to the operator;
- checkpoint and combined patch evidence;
- drift and recovery warnings.

The console does not execute apply in this slice. It may show the exact CLI
command that would apply the run.

### 9. Scenario And Live Provider Gates

Scenario harness normalization reads both events and v2 state. A scenario is
trusted only when:

- trust report is trusted;
- no worker failure is present;
- completion audit status is passed when the run is completed;
- expected checkpoint manifests and combined patch evidence exist;
- expected blockers appear in state or apply readiness.

Fake-provider scenarios remain the default gate. Live Codex and Claude smoke
tests remain opt-in through `WAYGENT_LIVE_PROVIDER`, but they must assert the
same shape:

- provider attempt recorded;
- provider cwd is the task worktree;
- task packet path is present;
- checkpoint manifest refs are manifest-backed paths;
- completion audit is passed for successful runs;
- malformed or failed provider output produces a useful failure class.

## Data Shape Changes

No legacy namespace is introduced.

Additive v2 state fields:

- `preflight`: source checkout classification, warning or blocker, checked_at.
- `worktrees`: task worktree manifests, source commit, path, branch, cleanup
  status.

Add derived API projection:

- `apply_readiness`: computed from state, completion audit, combined patch
  evidence, and reconciliation records.

Tighten existing records:

- `ProviderAttempt.failure_class` preserves normalized provider failure when
  present.
- verification records must include `kernel_result_ref`.
- completion audit `combined_apply_evidence` is required for apply-ready
  completed runs.

## Implementation Map

- `packages/orchestrator/src/orchestrator.ts`
  - Add run preflight.
  - Stop deleting existing run evidence by default.
  - Record preflight and worktree manifests.
  - Enforce actual changed-file scope before checkpoint creation.
- `packages/orchestrator/src/sourceCheckout.ts`
  - Return structured dirty classification suitable for state and events.
- `packages/orchestrator/src/stateReconciliation.ts`
  - Expand artifact, digest, event/state, checkpoint, and combined patch
    checks.
- `packages/orchestrator/src/runCommands.ts`
  - Keep `resume` and `apply` on the same apply-readiness contract.
  - Surface state drift and artifact-missing blockers consistently.
- `packages/provider-adapters/src/processAdapters.ts`
  - Preserve `failure_class`.
  - Reject unknown provider statuses instead of silently treating them as
    success.
  - Keep provider artifacts linked through `ProviderAttempt`.
- `packages/lens-projectors/src/apply.ts`
  - Add a v2-state-aware apply readiness projection or make the API use a
    dedicated orchestrator projection.
- `apps/api/src/server.ts`
  - Use v2 readiness for real run list and detail.
- `apps/console/src/uiModel.ts` and `apps/console/src/App.tsx`
  - Render v2 readiness, checkpoint evidence, drift blockers, and recovery
    commands.
- `packages/testkit/src/waygentScenarioHarness.ts`
  - Normalize replay from state plus events.
- `tests/waygent-scenarios/*.json`
  - Assert manifest-backed checkpoints and combined patch evidence.
- `tests/integration/waygent-live-provider-smoke.test.ts`
  - Assert live provider evidence against the same state contract.
- `docs/operations/waygent.md`
  - Document run preflight, duplicate run id behavior, apply readiness, and
    live-provider gates.

## Verification Strategy

Targeted tests:

```bash
bun test packages/orchestrator/tests/sourceCheckout.test.ts
bun test packages/orchestrator/tests/stateReconciliation.test.ts
bun test packages/orchestrator/tests/runCommandsV2.test.ts
bun test packages/orchestrator/tests/orchestratorApplyE2E.test.ts
bun test packages/provider-adapters/tests
bun test packages/lens-projectors/tests
bun test apps/api/tests apps/console/src
bun run waygent:scenarios
```

Full local gate:

```bash
skills/waygent/evals/run.sh
bun run check
bun run platform:demo
bun run check:legacy
bun run waygent:scenarios
bun run --cwd apps/console build
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
cd components/agentlens && .venv/bin/python -m pytest -q
git diff --check
```

Opt-in live gate:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

Live gates are skipped by default and should run only when the matching local
CLI is installed, authenticated, and acceptable for the current time and cost
budget.

## Rollout Strategy

1. Preflight and duplicate-run protection.
2. Provider normalization and changed-file scope enforcement.
3. Reconciliation expansion.
4. API and console readiness alignment.
5. Scenario harness and live-smoke contract upgrade.
6. Operations docs update and full gate.

Tasks 1-3 are shared-core and should run sequentially. API/console work can
start after the readiness projection shape is stable. Scenario harness work can
start after reconciliation records are stable. Live-smoke changes should land
after provider normalization.

## Design Risks

### Blocking Too Much At Run Preflight

Blocking `dirty_related` source changes is strict, but it prevents the worse
failure mode where Waygent silently ignores user edits because worktrees start
from committed `HEAD`. `dirty_unrelated` remains allowed with a visible warning.

### Duplicate Run Id Test Friction

Tests currently pass explicit run ids. Blocking duplicate run ids by default
requires tests to use fresh temp roots, generated run ids, or an explicit
replace option. This is acceptable because production evidence should not be
deleted by accident.

### Live Provider Instability

Codex and Claude may return prose, envelopes, malformed JSON, or partial task
claims. The adapter should normalize these into explicit failure classes and
artifacts, not broaden the success parser until it accepts ambiguous output.

### Console False Confidence

The console can make a run look ready if it follows event-only projections.
Real run views must prefer v2 state readiness and display drift blockers even
when old events look successful.

## Completion Definition

This design is complete when:

- `waygent run` records source preflight and blocks `dirty_related` work;
- duplicate run ids cannot silently erase previous evidence;
- live provider worker failures preserve useful `failure_class`;
- provider changed-file claims are checked against actual worktree diffs and
  task write policy;
- reconciliation blocks missing or corrupted provider, verification,
  checkpoint, and combined patch artifacts;
- API list and detail agree on apply readiness for real runs;
- console apply affordance follows the same readiness contract as
  `resumeRun()` and `applyRun()`;
- fake scenarios assert v2 completion audit and combined patch evidence;
- opt-in live smoke uses manifest-backed checkpoint expectations;
- no active legacy namespaces are introduced.

## References

- `docs/architecture/2026-05-21-waygent-runtime-v1-operational-maturity-design.md`
- `docs/architecture/2026-05-21-waygent-runtime-agentlens-product-parity-design.md`
- `components/agentlens/docs/spec/2026-05-21-waygent-recovery-aware-orchestration-apply-pipeline-design.md`
- `components/agentlens/docs/plan/2026-05-21-waygent-recovery-aware-orchestration-apply-pipeline.md`
- `docs/operations/waygent.md`
