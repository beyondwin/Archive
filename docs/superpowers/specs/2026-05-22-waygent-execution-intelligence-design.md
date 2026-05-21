# Waygent Execution Intelligence Design

Date: 2026-05-22
Status: Draft for user review

## Goal

Waygent should become faster and easier to trust by making each run explain
its execution cost, safe-wave decisions, barrier reasons, and artifact health.
This design combines two adjacent improvements into one cohesive slice:

1. expose a clear operator explanation for why a run executed in parallel,
   serially, or blocked;
2. reduce fixed runtime cost with centralized worktree management and an
   artifact index without weakening apply readiness.

The runtime source of truth remains `waygent.run_state.v2` plus AgentLens JSONL
events. Execution intelligence is a projection over Waygent-owned evidence, not
a second scheduler, a second trust engine, or a shortcut around verification.

## Current Context

Recent Waygent work established the active runtime boundary:

- Waygent owns scheduling, state, provider attempts, verification,
  checkpoints, recovery, apply, and AgentLens emission.
- Safe-wave parallel execution is implemented with a single run event/state
  writer and bounded provider concurrency.
- Active product paths are Waygent-native and v2-only; legacy AgentRunway
  routing is guarded out of the runtime.
- `apps/api` and `apps/console` can inspect real Waygent runs, but the operator
  surface still mostly shows safe-wave task ids instead of explaining cost,
  barriers, and evidence health.

The next useful boundary is therefore not more raw parallelism. It is a
measured execution model that shows where time went and why Waygent made each
safe or blocking decision, then uses the same evidence to reduce fixed costs.

## Non-Goals

- Do not relax checkpoint manifests, patch digest checks, dry-run evidence,
  completion audit, reconciliation, or clean-checkout apply rules.
- Do not trust provider claims without Waygent-owned verification evidence.
- Do not create a new runtime state file that competes with
  `waygent.run_state.v2`.
- Do not reintroduce KWS executor skills or AgentRunway as active Waygent
  routing.
- Do not introduce worktree reuse or pooling in the first implementation unless
  a separately approved follow-up design proves a narrower reuse policy is safe.
- Do not make live Codex or Claude provider smoke checks part of default local
  verification.

## Target Architecture

Waygent Execution Intelligence has three layers.

### Execution Evidence Layer

`packages/orchestrator` records durable evidence while the run executes:

- wave-level timing, concurrency, ready task ids, and withheld task reasons;
- task-level phase timing for worktree setup, provider execution,
  verification, checkpoint creation, checkpoint dry-run, and total task
  duration;
- worktree source head, worktree path, branch, setup duration, and cleanup
  status;
- an artifact index entry for every run artifact that matters to inspection,
  reconciliation, or apply readiness.

The existing run execution context remains the only writer for event sequence
assignment and run state flushing. Task workers may write task-local artifacts
through Waygent helpers, but generated artifact metadata must be registered
before the run advances past the relevant phase.

### Projection Layer

An execution explanation projection converts durable evidence into an operator
model:

- which tasks ran in each safe wave;
- which tasks were withheld and why;
- which dependencies, file claims, risk levels, missing checkpoints, failures,
  stale activity, or dirty source conditions serialized the run;
- which phase dominated runtime cost;
- which artifacts support apply readiness;
- whether the artifact index and byte-level artifact validation agree.

This projection should live in `packages/lens-projectors` so `inspect`, API,
and console read one shared explanation model. Orchestrator code may call the
projector for `inspect`, but it should not maintain a separate explanation
shape. The projection must read from `waygent.run_state.v2`, AgentLens events,
and indexed artifact metadata; it must not make apply readiness decisions by
itself.

### Operator Surface Layer

Waygent exposes the projection through existing product surfaces:

- `waygent inspect --json` returns structured execution intelligence fields.
- `waygent explain --last` includes human-readable cost and barrier summaries
  in addition to failure/recovery guidance.
- `apps/api` includes execution intelligence in run detail responses.
- `apps/console` upgrades the safe-wave section from task-id listing to a run
  explanation: parallelized tasks, serialized barriers, cost hotspots, and
  evidence health.

## Components

### ExecutionPhaseTiming

`ExecutionPhaseTiming` is a small structured shape for phase durations. It
extends existing task timing instead of replacing it.

Required phases:

- `worktree_setup`;
- `provider`;
- `verification`;
- `checkpoint`;
- `checkpoint_dry_run`;
- `total`.

Each phase records `started`, `completed`, and `duration_ms` when available.
Missing optional timing should be explicit rather than inferred from unrelated
timestamps.

### WorktreeManager

`WorktreeManager` centralizes the current task worktree preparation behavior.
Its first version records and measures; it does not optimize by reuse.

Responsibilities:

- prepare one isolated worktree per task;
- record source commit, worktree path, branch, and setup timing;
- return a `WaygentWorktreeManifest` compatible with `waygent.run_state.v2`;
- extend the worktree manifest contract to record cleanup status as `active`,
  `removed`, `failed`, or `unknown`;
- keep task worktree mutation isolated from the source checkout.

The manager should be used by `TaskExecutor`, not by chat context or host
subagents.

### ArtifactIndex

`ArtifactIndex` is a run-local index of artifacts written by Waygent. Each
entry records:

- artifact ref;
- media type;
- sha256;
- byte length;
- producer phase;
- task id when applicable;
- created timestamp.

The index should cover task packets, provider stdin/stdout/stderr, worker
results, kernel results, checkpoint patches, checkpoint manifests, checkpoint
dry-run evidence, combined apply patches, combined dry-run evidence, and
decision packets.

The index is an acceleration and explanation structure. Reconciliation still
confirms critical digests against the actual artifact bytes before marking a
run apply-ready.

### ExecutionExplanationProjection

`ExecutionExplanationProjection` is the operator-facing model. It should answer
four questions:

1. Why did this run execute in parallel, serially, or blocked?
2. Which barrier or phase consumed the most time?
3. Which artifacts prove the run is safe or unsafe to apply?
4. What plan-structure change would likely improve the next run without
   weakening trust gates?

The first version should stay descriptive. It may recommend splitting file
claims, reducing high-risk task scope, or adding explicit dependencies, but it
must not automatically rewrite plans.

## Data Flow

1. `runWaygent` starts a v2 run and computes the durable safe-wave projection.
2. The orchestrator records the selected safe wave and withheld task reasons.
3. `TaskExecutor` asks `WorktreeManager` to prepare each task worktree and
   records worktree setup timing.
4. Provider execution, verification, checkpoint creation, and checkpoint
   dry-run record phase timing and artifact index entries.
5. The single run writer replays task results into ordered events and
   `waygent.run_state.v2`.
6. Completion audit materializes combined apply evidence from verified
   checkpoints.
7. Reconciliation uses the artifact index to find expected artifacts, then
   validates required bytes and digests from the filesystem.
8. The execution explanation projection builds inspect/API/console output from
   run state, events, safe-wave records, timing records, and artifact health.

## Error Handling

Execution intelligence must fail closed around trust boundaries.

- If worktree setup fails, the affected task becomes blocked or failed with
  recorded evidence. Successful sibling task evidence remains intact.
- If artifact index registration fails for a required artifact, the run stops
  instead of continuing with an incomplete evidence map.
- If an artifact index entry disagrees with the actual artifact bytes,
  reconciliation treats it as `state_drift` or `artifact_missing` and keeps
  apply readiness blocked.
- If explanation projection fails, inspect/explain may report partial
  explanation data, but projection failure must not turn a blocked run into a
  ready run.
- If worktree cleanup fails, cleanup status is recorded. Cleanup failure is not
  automatically an apply blocker unless it affects artifact integrity, source
  checkout cleanliness, or reconciliation.
- If a task in a safe wave crashes, Waygent records the failed task evidence and
  preserves completed sibling results before recomputing the next projection.

## Testing Strategy

### Unit Tests

- `WorktreeManager` records source head, setup duration, worktree path, and
  cleanup status.
- `ArtifactIndex` records ref, sha256, byte length, producer phase, and task
  id; duplicate refs are deterministic.
- `ExecutionExplanationProjection` reports safe-wave membership, withheld
  reasons, timing hotspots, and artifact health.

### Orchestrator Integration Tests

- A multi-task safe wave records wave timing, task phase timing, and artifact
  index entries.
- Provider crash in one parallel task does not erase sibling task evidence.
- Checkpoint, dry-run, and combined patch artifacts appear in the artifact
  index.
- Index drift or missing indexed artifacts produce reconciliation blockers.
- Apply readiness remains blocked unless checkpoint, dry-run, completion audit,
  and reconciliation evidence all pass.

### API And Console Tests

- API run detail includes execution explanation fields for real v2 runs.
- Console renders parallelized tasks, serialized barriers, cost hotspots, and
  evidence health.
- Blocked runs, partial projection data, and runs without timing records render
  without breaking the UI.

### Verification Gate

Default verification for this slice:

```bash
bun run check
bun run waygent:scenarios
bun run platform:demo
bun run check:legacy
bun run --cwd apps/console build
git diff --check
```

The legacy Python AgentLens tree has been removed; do not add Python AgentLens
pytest back to the active gate.

## Phased Implementation

### Phase 1: Explain Current Execution

Add the explanation projection over existing safe-wave state, task timing,
withheld reasons, completion audit, drift, and apply readiness. Expose it
through `inspect --json`, API run detail, and a first console section.

Phase 1 is complete when an operator can see why a run was parallelized,
serialized, or blocked without changing runtime semantics.

### Phase 2: Measure Fixed Cost Precisely

Introduce `ExecutionPhaseTiming` and `WorktreeManager` measurement while
preserving one isolated worktree per task. Record provider, worktree,
verification, checkpoint, dry-run, wave, and total task costs.

Phase 2 is complete when the projection can identify the dominant fixed-cost
phase for a run.

### Phase 3: Artifact Index And Reconciliation Acceleration

Introduce `ArtifactIndex` and move reconciliation lookup to index-assisted
artifact discovery. Keep byte-level digest validation for required readiness
artifacts.

Phase 3 is complete when reconciliation can use the index while still catching
missing artifacts, digest drift, and byte-length drift.

### Phase 4: Operator Feedback Loop

Polish `waygent explain` and console output so operators can improve the next
plan. Recommended feedback should focus on file-claim splits, unnecessary
high-risk serialization, missing dependencies, and expensive fixed phases.

Phase 4 is complete when the operator can see what made the run slow and which
trust-preserving plan change would likely help.

## Acceptance Criteria

- `inspect`, API, and console explain safe-wave parallelism, serialization, and
  blockers from durable evidence.
- Runs record provider, worktree, verification, checkpoint, reconciliation, and
  wave cost breakdowns.
- Worktree preparation is centralized without introducing worktree reuse in the
  first pass.
- Artifact index entries exist for readiness-critical artifacts.
- Reconciliation uses the index only as a lookup aid and still validates
  required artifact bytes and digests.
- Apply readiness, checkpoint dry-runs, completion audit, and no-legacy guards
  remain at least as strict as they are now.
- Default verification commands pass.

## Review Checklist

Before implementation planning, confirm:

- the design keeps `waygent.run_state.v2` as runtime source of truth;
- the artifact index cannot authorize apply readiness alone;
- console/API additions are projections, not new mutation paths;
- WorktreeManager centralizes current behavior before optimizing it;
- no step revives AgentRunway or KWS executor skills as active routing.
