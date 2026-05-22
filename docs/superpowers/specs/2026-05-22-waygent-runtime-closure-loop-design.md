# Waygent Runtime Closure Loop Design

Date: 2026-05-22
Status: Draft for user review

## Goal

Waygent should close the remaining gap between "a provider produced useful
work" and "the runtime can safely explain, recover, and apply that work."
Recent work already made Waygent v2-only, moved Lens inspection to TypeScript,
added operational maturity projections, and surfaced apply blockers. The next
step is to make those pieces converge into one runtime closure loop:

1. classify checkpoint dry-run conflicts as first-class recovery evidence;
2. make CLI, API, and console read the same v2 state and readiness truth;
3. separate live-provider cost and startup noise from actual execution
   outcomes.

This is intentionally one combined slice. The three improvements share the same
operator boundary: after a run blocks, Waygent must say what happened, which
state is authoritative, and what the next safe action is. Splitting the work
would risk improving one surface while leaving another surface to report a
different diagnosis.

## Observed Runtime Signal

The latest real Codex-backed Waygent run for the operational maturity loop
shows the current gap:

- provider execution succeeded and produced a normalized worker result;
- Waygent kernel verification passed all recorded commands;
- checkpoint manifest and patch artifacts were written;
- checkpoint dry-run failed because the patch no longer applied cleanly to the
  source checkout;
- the final task state became `verified` with no `checkpoint_refs` and
  `latest_failure_class: "missing_checkpoint"`;
- `explain --last` reported `missing_checkpoint`, which hides the stronger
  fact that the checkpoint existed but failed dry-run with source-basis
  conflicts;
- provider runtime dominated total cost, and provider stderr contained large
  amounts of plugin and skill-loader noise that should be summarized without
  being treated as runtime failure.

The dry-run evidence included concrete `git apply --check` failures for
`docs/operations/verification.md`, `docs/operations/waygent.md`, and
`graphify-out/*`. The runtime should preserve that evidence and report the
blocker as a recoverable checkpoint/source-basis conflict, not as a missing
checkpoint.

## Non-Goals

- Do not weaken checkpoint manifests, patch digest checks, checkpoint dry-run
  evidence, completion audit, reconciliation, combined patch evidence, or
  clean-checkout apply rules.
- Do not let provider-reported success mark a run ready for apply.
- Do not replace `waygent.run_state.v2` with event-derived readiness when v2
  state exists.
- Do not make Codex or Claude live smoke checks part of default verification.
- Do not reintroduce AgentRunway, KWS CPE, or KWS CME routing.
- Do not automatically rewrite plans or mutate source files from diagnostic
  recommendations.
- Do not hide raw provider stdout or stderr artifacts. Operator summaries are
  derived views over preserved evidence.

## Design Principles

1. `waygent.run_state.v2` remains the runtime source of truth.
2. Apply readiness stays stricter than diagnostic maturity projections.
3. A checkpoint that exists but fails dry-run is not missing; it is a concrete
   conflict that needs a different recovery path.
4. CLI, API, and console must share the same projector outputs instead of
   recomputing state independently.
5. Provider cost and provider noise are operational signals. They should shape
   the next run, but they should not override kernel verification or apply
   readiness.
6. The final acceptance evidence must include a replayable blocked fixture and
   an offline dogfood run.

## Target Architecture

The runtime closure loop has three layers that land in order.

### Layer 1: Checkpoint Conflict Recovery

`dryRunCheckpointPatch` should return enough structured evidence for the
runtime to distinguish these cases:

- checkpoint manifest missing;
- checkpoint patch missing;
- checkpoint digest mismatch;
- checkpoint patch dry-run failed because the source checkout no longer
  matches the checkpoint basis;
- checkpoint patch dry-run failed for another patch application reason;
- empty patch passed as explicit no-op evidence.

The first implementation should classify `git apply --check` failures that
contain patch apply conflict messages as `needs_rebase`. This fits the existing
failure class vocabulary and tells the operator that the candidate checkpoint
must be regenerated or rebased against current source. `missing_checkpoint`
should remain reserved for cases where Waygent cannot find a valid manifest or
patch artifact.

Task execution should record dry-run failures in v2 state:

- keep the checkpoint manifest and patch artifact indexed;
- store checkpoint dry-run evidence ref in the task or completion audit path;
- set `latest_failure_class` to `needs_rebase` for source-basis conflicts;
- keep `checkpoint_refs` empty until dry-run passes;
- append a `runway.apply_dry_run_result` event with the structured reason,
  failed files when available, and evidence ref.

The task status can remain blocked when dry-run fails. If the runtime keeps the
intermediate `verified` status for compatibility, every projector and recovery
path must still treat non-null `latest_failure_class` plus empty
`checkpoint_refs` as a blocker. Prefer a clearer blocked status if the contract
and tests can be updated without widening scope.

`explainRun` should prioritize checkpoint dry-run blockers above generic
missing-checkpoint text:

```text
task_x blocked by needs_rebase: checkpoint patch dry-run failed against current source; files: docs/operations/waygent.md
```

`resumeRun` should map this blocker to reviewable actions such as:

- `inspect_run`;
- `regenerate_checkpoint`;
- `rebase_checkpoint`;
- `human_decision`.

If adding new action strings would create broad contract churn, the first pass
may use existing actions, but the summary must still name `needs_rebase` and
the dry-run evidence.

### Layer 2: State-Truth Alignment Across Surfaces

Waygent should have one shared run-read model used by:

- `statusRun`;
- `inspectRun`;
- API run list and run detail;
- console run list and run detail.

The read model should prefer `waygent.run_state.v2` when present:

- run status from v2 status and lifecycle outcome;
- apply status from `projectApplyReadinessFromState`;
- trust/failure summaries from events as replay evidence;
- operational maturity from v2 state plus events;
- state-read errors as explicit blockers when v2 state is missing, invalid, or
  unsupported.

Event-derived status remains useful only as fallback for historical or partial
run roots. A real v2 run must not show different answers between:

```bash
waygent status --last
waygent inspect --last
GET /runs
GET /runs/:runId
console run list
console run detail
```

This layer should introduce a small shared helper in `packages/orchestrator` or
`packages/lens-projectors` rather than duplicating v2 status logic inside API
and console. API and console can still shape the data for presentation, but the
classification should come from the same source.

The console should display the closure loop as dense operational evidence:

- top blocker from v2 state or operational maturity;
- apply readiness state and reason;
- checkpoint dry-run conflict files or summary;
- provider phase hotspot;
- provider stderr noise counts;
- next safe action.

The console must not enable apply unless the shared apply readiness projection
is `ready`.

### Layer 3: Provider Cost And Noise Hygiene

Provider readiness already records process evidence and stderr summaries. The
next step is to make that evidence more useful for plan shaping and operator
diagnosis.

Provider cost should be split into:

- startup/configuration noise before useful provider work;
- provider execution duration;
- result parsing and normalization;
- verification time after provider output;
- checkpoint and dry-run time after verification.

Waygent does not need perfect sub-process tracing in the first pass. It should
at least preserve the existing provider phase duration and add read-only
recommendations when:

- provider duration dominates total run time;
- stderr has high plugin-manifest or skill-loader counts;
- provider exits successfully but stderr contains repeated startup warnings;
- provider readiness is `ready` but local configuration cleanup would reduce
  noise.

Provider noise summaries should remain bounded:

- total line count;
- category counts;
- short samples per category;
- no secrets;
- raw artifact refs preserved for audit.

The readiness projection should avoid treating known startup noise as failure
when exit code and normalized worker result are successful. It should recommend
configuration cleanup separately from runtime recovery.

## Data Flow

1. Provider adapter records process evidence and bounded stderr summary.
2. Task executor runs kernel verification and checkpoint creation.
3. Checkpoint dry-run emits structured result and evidence artifact.
4. Task executor updates v2 task state with precise checkpoint/rebase blocker.
5. Completion audit and reconciliation keep apply readiness blocked until all
   checkpoint refs, combined patch evidence, and dry-run evidence pass.
6. Shared run-read model projects status, blocker, readiness, maturity, cost,
   and provider signals.
7. CLI, API, and console render the same diagnosis.

## Error Handling And Recovery

Checkpoint-related failure classes should mean different things:

- `missing_checkpoint`: no usable checkpoint manifest or patch exists.
- `artifact_missing`: an indexed artifact disappeared after being recorded.
- `state_drift`: recorded digest or state evidence no longer matches bytes.
- `needs_rebase`: checkpoint patch exists but fails dry-run against the current
  source checkout.
- `unsafe_apply`: apply would mutate source without the required readiness
  evidence.

For `needs_rebase`, Waygent should stop before apply, preserve the checkpoint
artifacts, expose dry-run stderr, and recommend checkpoint regeneration or
human decision. It should not retry apply automatically from chat context.

For provider noise, Waygent should classify configuration warnings as
diagnostic evidence. It should not block apply only because stderr contains
plugin or skill-loader warnings when provider output normalized and
verification passed.

## Testing Strategy

Add focused tests before implementation code:

- checkpoint dry-run conflict fixture that creates a valid checkpoint patch and
  then changes source so `git apply --check` fails;
- task executor regression proving the run state records `needs_rebase`, not
  `missing_checkpoint`, when dry-run fails after checkpoint creation;
- `explainRun` and `resumeRun` tests for checkpoint conflict blockers;
- API list/detail parity tests proving v2 status and apply readiness match CLI;
- console model tests proving run list and detail use shared v2 readiness;
- provider readiness tests for successful process with noisy stderr;
- runtime-cost tests for provider-dominated run recommendations;
- dogfood or scenario replay gate that includes the checkpoint conflict case.

Default verification for the implementation plan should include:

```bash
bun test packages/orchestrator/tests/checkpointArtifacts.test.ts packages/orchestrator/tests/taskExecutor.test.ts packages/orchestrator/tests/runCommandsV2.test.ts
bun test apps/api/tests/api.test.ts apps/console/src/uiModel.test.ts packages/lens-projectors/tests/operationalMaturity.test.ts packages/provider-adapters/tests/providerLogSummary.test.ts
bun run check
bun run waygent:scenarios
bun run waygent:dogfood
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

Run native kernel tests only if the implementation touches `native/kernel`.
Run live provider smoke tests only when explicitly opted in:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

## Implementation Shape

The implementation plan should be phased:

1. checkpoint dry-run reason model and tests;
2. task state and recovery wiring;
3. shared run-read/status model;
4. API and console parity;
5. provider cost/noise projection refinements;
6. docs, scenario fixtures, dogfood, and Graphify refresh.

Parallel work is safe only after the checkpoint reason model is stable.
Surface work can split across API and console if they both consume the shared
read model. Orchestrator state mutation, checkpoint artifacts, and recovery
logic should remain sequential.

## Acceptance Criteria

- A checkpoint patch that exists but fails dry-run is reported as
  `needs_rebase` or an equivalent source-basis conflict, not as a missing
  checkpoint.
- `explain --last` names the precise blocker and points to dry-run evidence.
- `resume --last` does not offer apply for checkpoint conflict runs.
- CLI status, CLI inspect, API list, API detail, console list, and console
  detail agree on v2 run status and apply readiness.
- Provider stderr startup noise is summarized and preserved without turning a
  successful provider attempt into a failure.
- Runtime-cost recommendations mention provider-dominated runs when provider
  time is the top hotspot.
- `bun run waygent:dogfood` still passes.
- `git diff --check` passes.
