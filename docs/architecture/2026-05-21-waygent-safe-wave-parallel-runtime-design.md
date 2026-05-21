# Waygent Safe-Wave Parallel Runtime Design

## Goal

Waygent must get faster without weakening the trust loop that now protects
provider execution, checkpoint sealing, apply readiness, and AgentLens replay.
The highest-leverage improvement is safe-wave parallel execution with a single
event and state writer.

The runtime should keep the same quality bar:

1. Scheduler-approved safe waves are the only source of parallelism.
2. Providers stay bounded workers in isolated task worktrees.
3. Kernel verification, diff-scope validation, checkpoint manifests, dry-run
   evidence, completion audit, and reconciliation remain mandatory.
4. AgentLens events stay replayable and ordered.
5. `waygent.run_state.v2` remains the authoritative execution state.

## Source Audit Basis

This design is based on the current source state at commit `9928c2c`:

- `packages/orchestrator/src/orchestrator.ts`
  - `runWaygent()` computes a scheduler safe wave but currently executes each
    task with `for ... await runOneTask(taskId)`.
  - `runOneTask()` creates a per-task worktree, task packet, provider attempt,
    verification records, diff-scope result, checkpoint, and task state update.
  - `providerAttempts`, `verificationRecords`, and `sequence` are mutable
    run-level variables shared by every task.
- `packages/runway-control/src/scheduler.ts`
  - `computeSafeWave()` already rejects dependency blockers, missing
    checkpoints, terminal failure barriers, stale activity, high-risk
    conflicts, and writable file-claim conflicts.
  - Therefore tasks in the same safe wave are the correct parallel execution
    unit.
- `packages/orchestrator/src/runState.ts`
  - `writeRunStateV2()` writes the entire state file. Concurrent read-modify
    writes would risk lost updates.
- `packages/lens-store/src/eventJournal.ts`
  - `appendEvent()` appends one JSONL event at a time. Concurrent sequence
    assignment would risk duplicate or out-of-order event numbers.
- `packages/orchestrator/src/checkpointArtifacts.ts`
  - `dryRunCheckpointPatch()` writes a fixed `.waygent-dry-run.patch` file in
    the source checkout. This must be replaced before parallel checkpoint
    dry-runs can be safe.
  - `createCombinedCheckpointPatchArtifact()` already runs after task
    checkpoints and should remain a terminal run-level barrier.
- `packages/provider-adapters/src/processAdapters.ts`
  - Codex and Claude adapters normalize provider process output, but provider
    output edge cases need replay fixtures so speed work does not regress live
    adapter behavior.
- `packages/orchestrator/src/stateReconciliation.ts`
  - Reconciliation is a strong completion barrier, but it re-reads many
    artifacts at the end of the run. It can later become index-assisted without
    dropping digest checks.

## Non-Goals

- Do not skip verification, checkpoint validation, dry-runs, completion audit,
  or reconciliation for speed.
- Do not let providers write AgentLens events or mutate the source checkout.
- Do not parallelize tasks outside the scheduler's safe wave.
- Do not introduce cloud queues, remote workers, or multi-user runtime
  behavior.
- Do not reintroduce KWS CPE/CME as Waygent runtime dependencies.
- Do not make live provider smoke checks part of default local verification.

## Design Principles

### Parallelism Is A Scheduler Permission

Waygent can execute tasks concurrently only after `computeSafeWave()` has
withheld tasks that are unsafe to run together. Dependency checkpoints,
writable file claims, high-risk tasks, stale activity, and terminal failures
stay serializing barriers.

### Task Work Is Parallel, Run Truth Is Serial

Task-local operations may run concurrently:

- task worktree preparation;
- task packet artifact creation;
- provider process execution;
- verification commands inside that task;
- actual changed-file discovery;
- task checkpoint creation.

Run-level truth stays serial:

- event sequence assignment;
- event journal append;
- `waygent.run_state.v2` mutation and flush;
- safe-wave completion decisions;
- combined apply patch materialization;
- final completion audit and reconciliation.

### Quality Gates Are Reordered, Not Removed

The runtime may move independent work earlier or run it in parallel, but it
must not replace evidence checks with provider claims. Provider success remains
insufficient until Waygent records kernel verification, diff-scope validation,
checkpoint evidence, and apply-readiness evidence.

### Speed Work Must Be Measurable

Every phase should add evidence that explains where time is being spent:
provider duration, worktree setup duration, verification duration, checkpoint
duration, reconciliation duration, and total wave duration.

## Target Architecture

### Run Execution Context

Introduce a run-scoped execution context around `runWaygent()`:

- owns the in-memory `WaygentRunStateV2`;
- owns event sequence allocation;
- exposes `emit(eventIntent)` for ordered journal writes;
- exposes `mutateState(reducer)` for serialized state updates;
- flushes state at controlled checkpoints;
- records phase timing and task timing.

This context is the only code allowed to append events or write run state
during execution. Task workers return results; they do not directly write
run-level truth.

### Task Execution Result

Refactor `runOneTask()` into a task executor that returns a structured result:

- task id and candidate id;
- worktree manifest;
- task packet artifact metadata;
- provider attempt metadata;
- worker result artifact metadata;
- verification records;
- diff-scope result;
- checkpoint refs;
- task status patch;
- event intents in local order;
- timing summary.

The executor may still write task-local artifacts because their paths are
namespaced by task id or attempt id. It must not mutate shared arrays, append
events, or overwrite `state.json`.

### Safe-Wave Parallel Executor

Add an `executeSafeWave()` orchestration unit:

1. Receive the scheduler-approved safe-wave task ids.
2. Start eligible task executors with bounded concurrency.
3. Preserve task-local verification command ordering.
4. Collect task results and failures.
5. Replay each result through the single writer in deterministic task order.
6. Recompute durable projection after the wave finishes.

Default concurrency should be conservative:

- fake provider: safe to use the full safe-wave width in tests;
- live providers: default to `2` to avoid local resource contention and
  provider rate-limit surprises;
- operator override: `WAYGENT_WAVE_CONCURRENCY` or a future CLI flag.

### Unique Dry-Run Scratch

Replace the fixed source-checkout `.waygent-dry-run.patch` path with a unique
scratch patch path. The scratch path can live under a temporary directory or a
run-local scratch artifact directory. The dry-run still executes from the
source checkout with `git apply --check <patch-path>`.

This is a prerequisite for safe parallel task checkpoint dry-runs.

### Provider Contract Replay

Add a replay fixture layer for provider process outputs:

- sanitized Codex JSONL output with telemetry envelopes and agent message
  worker JSON;
- sanitized Claude JSON and fenced JSON output;
- malformed output;
- provider-supplied failure classes;
- timeout and missing executable evidence.

Replay tests should call the same normalization code as live adapters. Live
smoke remains opt-in, while replay fixtures become the fast regression shield.

### Worktree Manager

After Phase 1, introduce a small worktree manager around the current
`prepareTaskWorktree()` helper:

- records source head, planned path, branch name, and cleanup status;
- centralizes clone/reset behavior;
- measures setup duration;
- later supports lazy creation, reuse, or pooling where safe.

The manager should keep one isolated worktree per task unless a later design
proves a shared worktree is safe for a narrower case.

### Artifact Index And Incremental Reconciliation

After Phase 1, add a run artifact index that records every artifact as it is
written:

- relative ref;
- media type;
- sha256;
- byte length;
- producer phase;
- task id when applicable.

`reconcileRunState()` can then validate expected refs against the index and
only re-read bytes when digest confirmation is required. This keeps the
completion barrier strong while reducing repeated filesystem scanning.

### Plan Cost Model And Dogfood Evidence

Add an inspection projection that explains expected and actual runtime cost:

- estimated waves;
- tasks per wave;
- withheld tasks and reasons;
- file-claim serial barriers;
- high-risk serial barriers;
- measured provider, worktree, verification, checkpoint, reconciliation, and
  total durations;
- whether the run was dogfooded through Waygent;
- replay, scenario, and live-smoke evidence refs when present.

This helps operators improve plan structure before execution and confirms that
faster runs still used the required trust loop.

## Phased Implementation

### Phase 1: Parallel Speed Path

Phase 1 includes:

1. unique dry-run scratch paths;
2. `RunExecutionContext` as the single event/state writer;
3. task execution results instead of direct run-level mutation;
4. bounded `executeSafeWave()` parallelism;
5. provider contract replay fixtures and tests;
6. timing evidence for task and wave durations.

Phase 1 is complete when an independent multi-task plan runs safe-wave tasks in
parallel while preserving existing apply readiness, checkpoint, reconciliation,
and scenario behavior.

### Phase 2: Fixed-Cost Reduction

Phase 2 includes:

1. `WorktreeManager`;
2. source-head and cleanup-status tracking;
3. worktree setup timing;
4. run artifact index;
5. index-assisted reconciliation.

Phase 2 is complete when the remaining non-provider runtime overhead is
measured and reduced without changing readiness semantics.

### Phase 3: Operator Feedback Loop

Phase 3 includes:

1. plan cost model projection;
2. inspect/API/console exposure of waves, serial barriers, and measured
   runtime segments;
3. dogfood evidence fields in run state or completion audit;
4. documentation for writing faster Waygent plans without bypassing trust
   gates.

Phase 3 is complete when an operator can see why a plan ran serially or
parallel, what cost each barrier added, and which evidence proves the run kept
the quality gates.

## Error Handling

- If any task executor crashes, the wave result records that task as blocked or
  failed with provider/process/kernel evidence when available.
- A task failure does not erase successful sibling task evidence. The single
  writer records all completed task results before recomputing the projection.
- If the single writer cannot append an event or flush state, the run must stop
  rather than continue without durable evidence.
- If reconciliation finds drift after a parallel run, apply readiness remains
  blocked through the existing drift blocker path.
- If bounded concurrency is configured below `1` or above the safe-wave width,
  Waygent normalizes it to a valid range and records the chosen value.

## Testing Strategy

Phase 1 tests:

- scheduler-approved independent tasks execute through a parallel safe wave;
- conflicting file claims still serialize through existing scheduler barriers;
- high-risk tasks still serialize;
- event sequences remain unique and ordered;
- state contains every provider attempt, verification record, checkpoint, and
  worktree manifest after parallel execution;
- dry-run scratch files do not collide under parallel checkpoint creation;
- provider replay fixtures cover Codex JSONL, Claude envelopes, malformed
  output, provider failure classes, timeout, and missing executable;
- existing `bun run check`, `bun run platform:demo`,
  `bun run waygent:scenarios`, and opt-in live provider smoke keep passing.

Phase 2 tests:

- worktree manager records source head and cleanup status;
- setup timings are present;
- artifact index records every task packet, provider artifact, kernel result,
  checkpoint patch, checkpoint manifest, dry-run evidence, and combined patch;
- reconciliation still catches missing artifacts and digest drift.

Phase 3 tests:

- plan cost model reports expected waves and withheld reasons;
- inspect/API/console show measured wave and task timings;
- dogfood evidence appears only when backed by recorded run evidence.

## Acceptance Criteria

- Phase 1 can be implemented and verified independently of Phase 2 and Phase 3.
- No default verification command becomes weaker.
- No provider claim is trusted without Waygent-owned verification.
- `waygent apply` remains blocked unless the v2 readiness projection is ready.
- Event and state writes are serialized through one runtime boundary.
- Parallel execution never writes a fixed scratch file in the source checkout.
- Documentation describes all six high-level improvements while the
  implementation plan executes Phase 1 first.
