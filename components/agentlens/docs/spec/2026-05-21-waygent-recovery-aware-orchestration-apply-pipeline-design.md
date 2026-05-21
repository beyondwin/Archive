# Waygent Recovery-Aware Orchestration And Apply Pipeline Design

| | |
|---|---|
| Date | 2026-05-21 |
| Status | Approved direction |
| Scope | Waygent orchestration, recovery, checkpoint artifacts, and explicit apply |
| Decision | Completed runs must contain apply-ready verified checkpoint artifacts |
| Related Runtime | `packages/orchestrator`, `packages/runway-control`, `packages/provider-adapters`, `packages/lens-store`, `apps/cli`, `skills/waygent` |

## 0. Decision

Extend Waygent with a recovery-aware orchestration loop and a full apply
pipeline.

The central invariant is:

> A Waygent run may be marked `completed` only when every verified task has a
> durable checkpoint artifact that `waygent apply` can validate and apply.

This closes the current runtime risk where `resumeRun()` can expose
`apply_verified_checkpoint` for a completed run, while `applyRun()` later blocks
with `missing_verified_checkpoint` because the run recorded only a logical
checkpoint reference such as `checkpoint_task_candidate` and did not materialize
the patch artifact that apply reads.

## 1. Current Failure

The current run path can produce this state:

1. `runWaygent()` dispatches a safe wave.
2. A worker returns `completed`.
3. Verification passes.
4. `mergeCandidate()` returns a checkpoint ref string.
5. The task records that ref in `checkpoint_refs`.
6. The run writes `completion_audit.status = passed`.
7. `resumeRun()` allows `apply_verified_checkpoint`.
8. `applyRun()` resolves the checkpoint ref as a patch path and blocks with
   `missing_verified_checkpoint`.

Root cause: the orchestration layer treats checkpoint refs as completion
evidence, but the apply layer treats checkpoint refs as patch artifacts. The
runtime contract does not force checkpoint artifact creation before completion.

## 2. Architecture

Waygent run execution becomes:

```text
dispatch
  -> review
  -> verify
  -> checkpoint
  -> apply_dry_run
  -> complete_or_recover
```

The `checkpoint` and `apply_dry_run` phases are required gates, not optional
apply-time details.

`runWaygent()` must not finish a successful task after verification alone. It
must create a checkpoint manifest, create or reference the patch artifact, check
that the patch can apply to the source checkout, and record that evidence in
state and events.

`resumeRun()` and `applyRun()` must derive their behavior from the same
artifact contract. A completed run that cannot prove apply readiness is a
blocked run, not a completed run with a hidden apply failure.

## 3. State Machine

The run-level state machine is:

```text
initializing
  -> running
  -> blocked | failed | completed
  -> applying
  -> applied | blocked | failed
```

The task-level state machine is:

```text
pending
  -> ready
  -> running
  -> needs_fix | blocked | failed | verified
  -> applied
```

The orchestration loop repeatedly computes a durable projection from task
state, releases the next safe wave, records provider attempts, runs review and
verification gates, creates checkpoints, and either schedules more ready work
or stops at a recovery barrier.

The loop is deterministic with respect to recorded state:

- no mutable worktree is created outside the scheduler-approved safe wave;
- dependent tasks are withheld until required checkpoints exist;
- terminal or human-decision failures stop automatic dispatch;
- state reconciliation runs before completion;
- apply readiness is part of completion, not a later best-effort check.

## 4. Checkpoint Artifact Contract

Every verified task writes a checkpoint manifest and patch artifact:

```text
artifacts/checkpoints/<task_id>/<candidate_id>.patch
artifacts/checkpoints/<task_id>/<candidate_id>.json
```

The manifest contains:

- `schema`
- `run_id`
- `task_id`
- `candidate_id`
- `patch_ref`
- `patch_sha256`
- `patch_byte_length`
- `changed_files`
- `source_base`
- `worktree_path`
- `verification_refs`
- `created_at`
- `dry_run_status`
- `dry_run_evidence_ref`

`checkpoint_refs` must store manifest paths or patch paths that resolve within
the run artifact tree. It must not store unresolved logical names as successful
completion evidence.

Patch creation should use the narrowest reliable source available:

1. use a kernel diff helper when available;
2. otherwise use `git diff --binary` in the candidate worktree against the
   recorded source base;
3. fail closed when the source base cannot be determined.

Empty patches are not automatically successful. The orchestration layer must
classify them using task intent:

- if the task is explicitly no-op or evidence-only, record a no-op checkpoint
  with review evidence;
- otherwise block with `missing_checkpoint` or `artifact_missing`.

## 5. Apply Pipeline

`waygent apply` reads checkpoint manifests, validates patch digests, and applies
only verified checkpoints.

The apply pipeline is:

1. resolve run id;
2. read `waygent.run_state.v2`;
3. reject if source checkout is dirty;
4. reject if completion audit did not pass;
5. load checkpoint manifest;
6. verify patch artifact exists;
7. verify patch sha256 and byte length;
8. run `git apply --check` against the source checkout;
9. apply patch;
10. run post-apply verification commands;
11. record `runway.apply_completed`, `runway.apply_blocked`, or
    `runway.apply_failed`;
12. update state to `applied`, `blocked`, or `failed`.

Apply is explicit. Workers never apply patches to the source checkout directly,
and chat context must not retry apply after `dirty_source_checkout` or failed
post-apply verification.

## 6. Completion Audit

`completion_audit.status = passed` requires all of the following:

- every task in the completed safe wave is verified;
- every verified task has at least one checkpoint manifest;
- every checkpoint manifest points to an existing patch artifact;
- every patch artifact digest matches its manifest;
- every patch has passed apply dry-run;
- verification evidence exists for every checkpoint;
- verification evidence is not older than the checkpoint it supports;
- state reconciliation has no unrepaired blockers;
- apply readiness is recorded in state and events.

If any condition fails, the run status is `blocked`, `lifecycle_outcome` is
`blocked`, and the runtime emits a decision packet with concrete next actions.

## 7. Recovery Policy

Failure handling is based on the next safe action.

| Failure class | Default action |
|---|---|
| `verification_failed` | Rerun verification once, then require decision packet. |
| `adapter_crashed`, `timeout`, `malformed_result` | Retry same provider within budget, then suggest provider switch. |
| `missing_checkpoint`, `artifact_missing`, `state_drift` | Block completion and create a checkpoint recovery decision packet. |
| `patch_apply_failed`, `needs_rebase`, `dirty_source_checkout` | Block apply and require source cleanup, rebase, or operator decision. |
| `post_apply_verification_failed` | Record failed apply, preserve evidence, and require operator decision. |
| `needs_plan_fix`, `needs_split`, `terminal_rejected` | Stop automatic dispatch and require plan or human decision. |

`resumeRun()` must expose actions that match the actual state:

- `apply_verified_checkpoint` only when manifests, patches, digests, dry-run
  evidence, and completion audit all pass;
- `retry_checkpoint_generation` when verification passed but checkpoint
  materialization failed;
- `rerun_verification` when checkpoint readiness depends on stale or failed
  verification;
- `switch_provider` when provider failures exhausted same-provider retry;
- `clean_source_checkout` when apply is blocked by source dirtiness;
- `human_decision` when the runtime cannot safely infer the next step.

## 8. Event And State Evidence

New or strengthened event families:

- `runway.checkpoint_created`
- `runway.checkpoint_failed`
- `runway.apply_dry_run_result`
- `runway.decision_packet_created`
- `runway.apply_blocked`
- `runway.apply_failed`
- `runway.apply_completed`
- `lens.trust_report_updated`

Events should include artifact references when they are central evidence. State
should include enough artifact paths for CLI, API, and console views to explain
why a run is apply-ready or blocked without scanning arbitrary files.

## 9. Console And CLI Impact

The CLI behavior changes in these ways:

- `waygent resume --last` no longer treats completed status alone as enough to
  offer apply;
- `waygent inspect --run <id>` shows checkpoint manifests and apply readiness;
- `waygent explain --last` reports checkpoint and dry-run barriers;
- `waygent apply --run <id>` reports digest mismatch, missing artifact, dirty
  source, dry-run failure, and post-apply verification failure distinctly.

The console should show:

- safe wave status;
- checkpoint readiness per task;
- apply dry-run status;
- decision packet actions;
- apply blockers and post-apply verification evidence.

## 10. Implementation Phases

### Phase 1: Close The Verified Checkpoint Gap

Goal: a successful `runWaygent()` run can be applied, and an unappliable run
cannot be marked completed.

Acceptance:

- an end-to-end test reproduces the current `completed -> resume allows apply
  -> apply blocks missing_verified_checkpoint` failure before the fix;
- `runWaygent()` writes checkpoint patch and manifest artifacts for verified
  tasks;
- `completion_audit.status = passed` requires resolvable checkpoint artifacts;
- `resumeRun()` allows `apply_verified_checkpoint` only when apply readiness is
  proven.

### Phase 2: Harden The Apply Pipeline

Goal: apply has first-class evidence and failure classes.

Acceptance:

- dirty source checkout blocks without retry;
- digest mismatch blocks;
- missing patch artifact blocks;
- `git apply --check` failure blocks before mutation;
- post-apply verification failure records `apply.failed`;
- successful apply updates state and emits apply completion evidence.

### Phase 3: Expand Recovery-Aware Orchestration

Goal: Waygent can continue safe work automatically and stop only at real
barriers.

Acceptance:

- the orchestration loop repeatedly dispatches safe waves until no automatic
  work remains;
- retryable provider failures consume retry budget;
- verification retry and provider switch decisions are recorded;
- stale activity, missing checkpoint, missing resume handler, and terminal
  failure remain scheduler barriers;
- decision packets contain concrete allowed and blocked actions.

## 11. Tests

Required verification commands:

```bash
bun test packages/orchestrator/tests packages/runway-control/tests
bun run waygent:scenarios
skills/waygent/evals/run.sh
bun run check
git diff --check
```

Focused tests should cover:

- `runWaygent -> resumeRun -> applyRun` success path;
- completed run with missing checkpoint artifact is impossible;
- completion audit fails when manifest digest does not match patch;
- apply blocks dirty source checkout;
- apply blocks dry-run failure;
- apply records post-apply verification failure;
- resume exposes checkpoint-specific recovery actions;
- safe wave loop continues after independent task completion;
- terminal failure creates a decision packet and stops dispatch.

## 12. Non-Goals

- Reintroducing KWS CPE/CME as active runtime dependencies.
- Letting workers write AgentLens or source checkout state directly.
- Supporting legacy unresolved checkpoint refs as successful apply evidence.
- Building cloud or distributed execution.
- Replacing AgentLens filesystem artifacts with SQLite as source of truth.

## 13. Open Implementation Notes

The implementation plan should decide exact helper placement, but the expected
boundaries are:

- `packages/orchestrator`: checkpoint artifact creation, completion audit,
  resume/apply command behavior, orchestration loop wiring;
- `packages/runway-control`: scheduler barriers, decision packet policy, retry
  recommendation;
- `packages/lens-store`: artifact digest helpers and artifact references;
- `native/kernel`: future diff/apply helper if TypeScript shelling is replaced
  with native kernel calls;
- `apps/console`: checkpoint/apply readiness display;
- `skills/waygent`: command contract and stop-rule updates.

The first implementation should stay local and deterministic. Live provider
smoke remains opt-in after offline scenario gates pass.
