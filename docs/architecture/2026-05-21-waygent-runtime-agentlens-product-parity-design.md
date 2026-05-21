# Waygent Runtime And AgentLens Product Parity Design

## Goal

Waygent becomes the product runtime that can replace the practical execution
capabilities previously proven by local KWS executor skills, without making
those skills part of the Waygent product.

The target product must work from both entrypoints:

- operator entrypoint: `skills/waygent` and the `waygent` CLI;
- product entrypoint: local API plus the AgentLens-backed console.

A run is complete only when the same execution can be started from the skill or
CLI, recorded as durable Waygent events, projected through AgentLens trust
views, queried through the API, and inspected in the console.

## Non-Goals

- Do not call `skills/kws-codex-plan-executor` or
  `skills/kws-claude-multi-agent-executor` from Waygent.
- Do not wrap KWS executor state formats or namespaces as product runtime
  dependencies.
- Do not preserve `kws-cpe.*`, `kws-cme.*`, or historical KWS orchestrator event
  families as active Waygent contracts.
- Do not treat demo fixtures as proof of runtime parity when a real `waygent
  run` path is required.

The KWS skills may remain in the repository as personal or historical executor
skills. They are not Waygent product components.

## Product Boundary

The active Waygent product boundary is:

- `skills/waygent`: natural-language operator entrypoint;
- `apps/cli`: stable command surface;
- `apps/api`: local product API and event stream;
- `apps/console`: run inspection UI;
- `packages/*`: contracts, scheduler, store, projectors, provider adapters,
  policy, context packing, and orchestrator;
- `native/kernel`: typed native execution and worktree boundary;
- `components/agentlens`: observability, evaluation, replay, and trust
  projection component.

AgentLens is downstream of Waygent execution. It reads filesystem JSONL events
and projection inputs, then exposes trust, failure, timeline, and evaluation
views. AgentLens must not mutate Waygent execution state.

## Runtime Model

`waygent run` owns the execution lifecycle:

1. resolve input from `--plan`, `--spec`, `--latest`, `--topic`, or a skill
   natural-language intent;
2. create a run id, isolated worktree, run state, event journal, and artifact
   root;
3. parse the implementation plan into a typed task graph;
4. select a provider profile and execution mode;
5. release only scheduler-approved safe-wave tasks;
6. dispatch workers through provider adapters;
7. normalize provider output into `WorkerResult`;
8. execute verification through the kernel boundary;
9. record evidence and update AgentLens-compatible events;
10. stop before apply unless the operator explicitly invokes `waygent apply`.

The fake provider remains the deterministic offline path. Codex and Claude
providers use the same worker result contract and must not write AgentLens
directly.

## AgentLens Integration

Waygent writes canonical `agentlens.event.v3` events under product namespaces:

- `platform.*` for run lifecycle;
- `runway.*` for plan, schedule, worker, verification, recovery, and apply
  gates;
- `kernel.*` for bounded execution evidence;
- `lens.*` for projection update notifications.

AgentLens consumes those events to build:

- timeline;
- trust report;
- failure summary;
- blocked decision packet;
- apply status;
- artifact and verification evidence views.

Filesystem JSONL remains the source of truth. SQLite remains a rebuildable
cache. API and console views must be reproducible from the filesystem event
journal.

## Skill Contract

`skills/waygent` is the only product skill entrypoint. It should provide:

- natural-language command mapping for run, status, events, inspect, explain,
  resume, and apply;
- stable examples for Korean and English requests;
- a command reference aligned with `apps/cli`;
- stop rules for missing plans, dirty apply, ambiguous latest/topic matches,
  provider failures, and failed verification;
- evals that prove the skill contract stays aligned with the CLI.

The skill stays thin. It translates intent and invokes the CLI; it does not
implement scheduling, provider execution, worktree mutation, trust scoring, or
direct AgentLens writes.

## API And Console Contract

The local API must read real Waygent run state, not only static demo fixtures.
Required surfaces:

- `GET /healthz`;
- run list with status, trust, apply state, and last event;
- run detail with task graph, safe wave, withheld tasks, and provider profile;
- ordered event stream for a run;
- trust and failure projections;
- resume recommendation or blocked decision packet;
- apply readiness and dirty-source blocker.

The console must make the operator answer four questions quickly:

- What is running or what ran last?
- Why is it trusted, failed, blocked, or still running?
- What evidence exists for verification?
- Is apply allowed, blocked, or already completed?

## Parity Checklist

Waygent should match the useful execution capabilities of the KWS executor
skills without depending on them:

- plan/spec/latest/topic resolution;
- isolated worktree per run;
- durable run state and event journal;
- task graph and file-claim ownership;
- safe-wave multi-agent scheduling;
- provider abstraction for fake, Codex, and Claude;
- context packet construction for tasks;
- verification evidence through the kernel boundary;
- failure barrier and recovery recommendation;
- resume from durable state;
- explicit apply with dirty checkout guard;
- completion audit with command evidence;
- AgentLens trust and timeline visibility.

## Milestones

### 1. Skill And CLI Contract Slice

Deliver a `skills/waygent` contract with evals and a CLI that supports
`run/status/events/inspect/explain/resume/apply` against real local run data.
`--latest` and `--topic` must resolve plan files deterministically.

Acceptance:

```bash
bun test apps/cli/tests packages/orchestrator/tests
bun run platform:demo
```

### 2. Durable Executor Core Slice

Move from demo lifecycle to real run lifecycle: run directory, worktree, state,
event journal, artifact root, task graph, safe wave, verification evidence, and
completion audit.

Acceptance:

```bash
bun run check
cd native/kernel && cargo test --workspace
```

### 3. Provider And Multi-Agent Slice

Implement provider adapters for Codex and Claude behind the same contract used
by the fake provider. Safe-wave release remains the only way to dispatch
parallel tasks.

Acceptance includes deterministic fake tests plus provider-boundary tests that
do not require live credentials for default local verification.

### 4. AgentLens Product Slice

Wire real Waygent runs through API and console views. The console must inspect a
run created by `waygent run`, not only bundled demo data.

Acceptance:

```bash
bun run check
cd components/agentlens && python -m pytest -q
```

### 5. Apply And Recovery Slice

Finish explicit apply, dirty-source blocking, resume decisions, retry policy,
and recovery evidence. Failed or blocked runs must explain the next allowed
operator action.

Acceptance includes tests for dirty apply, failed verification, blocked
dependencies, stale activity, and successful explicit apply.

## Verification Strategy

Every slice must include:

- contract tests for the command or event shape;
- runtime tests against filesystem state;
- AgentLens projection tests when event meaning changes;
- `bun run check`;
- Rust kernel checks when worktree, process, or kernel protocol behavior
  changes;
- AgentLens pytest when read compatibility or projection inputs change.

No slice is complete if the CLI works but the API/console cannot inspect the
same run, or if the console works only from static fixtures.

## Migration Policy

Waygent may use KWS executor behavior as a parity reference, but not as a
runtime dependency. Product docs should describe Waygent as the active path and
refer to KWS skills only as repository-local historical or personal executor
skills when necessary.

Legacy `agentrunway.*` read compatibility may remain in AgentLens where it
protects historical data. New Waygent runtime events use Waygent product
namespaces only.
