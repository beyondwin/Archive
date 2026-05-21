# Waygent Contract-First Unified Agent Platform Design

| | |
|---|---|
| Date | 2026-05-21 |
| Status | Approved direction, pre-implementation |
| Scope | Contract reconciliation before the Full Rust Agent Platform rewrite |
| Supersedes | Direct execution of `2026-05-21-full-rust-agent-platform-phase-1-skeleton-contracts.md` as written |
| Preserves | The Full Rust Agent Platform target from `2026-05-21-full-rust-agent-platform-rewrite-design.md` |

## 0. Decision

Keep the Full Rust Agent Platform direction, but do not start the Rust skeleton
plan as currently written. The next implementation slice must be a contract
reconciliation slice that makes the run, event, store, evaluator, API, and
harness contracts authoritative before any new crate layout is fossilized.

The target product is Waygent, a single agent platform with these roles:

- Waygent: the user-facing product and orchestration entrypoint.
- Agent Orchestrator: durable state machine, scheduling, recovery, and operator
  decisions.
- AgentRunway: the implementation-execution role and policy set.
- AgentLens: evidence, evaluation, trust reports, read models, and dashboard.

Waygent is not a revival of the old `kws-cpe` / `kws-cme` split.

## 1. Findings From Current Source And Harness Review

### 1.1 Contract Fragmentation

There are multiple competing event shapes:

- `agentlens.event.v1` uses `type` / `ts`.
- `agentlens.event.v2` uses `event_type` / `occurred_at` and is currently
  AgentRunway-specific.
- The current Rust Phase 1 plan proposes new `agent.*` schema names.

The rewrite must not introduce another schema dialect. `agent-contracts` must
own the platform contracts already implied by AgentLens and AgentRunway rather
than inventing a parallel `agent.event.v1` shape.

### 1.2 Legacy KWS Split Drift

Repo guidance has moved away from the old `kws-cpe` and `kws-cme` split. Those
names may remain as legacy import labels, but the new runtime architecture must
not use them as first-class product roles or event namespaces.

### 1.3 AgentLens v2 Is Not End To End

AgentLens has `run.v2`, `event.v2`, `final.v2`, and `eval.v2` schemas, but core
evaluation and query paths still project v1 fields such as `agent_outcome`.
Before Rust store or API work starts, the evaluator and read models need a
version-aware normalization contract.

### 1.4 AgentRunway Runtime Has The Best Execution Substrate

AgentRunway already has the strongest execution semantics:

- safe waves and file-claim conflict detection;
- checkpoint-gated dependency release;
- durable projection;
- decision packets;
- recovery barriers;
- merge queue and candidate isolation;
- deterministic fake adapter evals.

The weakness is not the model. The weakness is that control flow is too
centralized in the runner and several contracts are duplicated across modules.
The rewrite should lift the durable projection into a single orchestrator state
machine instead of porting the runner shape one-to-one.

### 1.5 Harness Confidence Is Uneven

AgentRunway evals are useful deterministic runtime tests. The Codex executor
harness is mostly static contract validation. The Claude executor harness is
closer to live behavior but can touch real `~/.claude` state and launch real
Claude processes. The new platform needs a unified deterministic harness first,
with live model smoke tests kept opt-in.

## 2. Target Architecture

```text
waygent/
  crates/
    agent-core/
    agent-contracts/
    agent-store/
    agent-orchestrator/
    agent-runway/
    agent-eval/
    agent-adapters/
    agent-server/
    agent-cli/
  apps/
    lens-web/
  tests/
    fixtures/
    e2e/
  docs/
    architecture/
    contracts/
    operations/
```

### 2.1 `agent-core`

Owns primitives shared by every role:

- run, task, workspace, checkpoint, candidate, and event ids;
- outcome, risk, severity, status, and failure classes;
- deterministic clocks;
- environment and config resolution;
- shared error taxonomy.

It must not depend on store, adapters, server, evaluator, or orchestrator
implementation crates.

### 2.2 `agent-contracts`

Owns every schema and typed payload definition:

- run headers;
- event envelopes;
- final and eval artifacts;
- manifest and sealing;
- trust report and projection artifacts;
- typed core orchestration event payloads;
- version-aware validation and normalization.

No other crate may define competing event or artifact shapes.

### 2.3 `agent-store`

Owns durable persistence:

- filesystem JSON artifacts as source of truth;
- append-only local event journal;
- local-first outbox for external emission;
- manifest sealing and hash verification;
- SQLite materialized read model;
- backfill and replay;
- retention and garbage collection.

SQLite remains rebuildable. It may accelerate run lists, event metadata, trust
reports, projection summaries, failure counts, and observability health, but it
must never be the only copy of critical evidence.

### 2.4 `agent-orchestrator`

Owns the durable state machine:

- plan/spec loading through contract interfaces;
- dependency graph;
- safe-wave selection;
- stale activity and blocked dependency barriers;
- retry budget and recovery policy;
- human decision packet creation;
- durable resume planning;
- operator-facing projection.

This crate decides the next action from durable evidence. CLI, server, web,
workers, reviewers, and verifiers do not bypass it.

### 2.5 `agent-runway`

Owns execution policy for implementation plans:

- task packet construction;
- worktree lifecycle;
- worker candidate flow;
- reviewer and verifier gates;
- candidate ranking;
- merge and apply policy;
- acceptance evidence collection.

It is a first-class role, not the entire platform.

### 2.6 `agent-eval`

Owns judgment:

- evidence projection;
- final claim versus evidence comparison;
- trust report generation;
- failure checks;
- degraded observability classification;
- version-aware evaluation of v1, v2, and new unified runs.

Agent output is always treated as a claim, not truth.

### 2.7 `agent-adapters`

Owns process integration:

- local deterministic fake adapter;
- Codex adapter;
- Claude adapter;
- process supervision;
- cancellation and timeout behavior;
- transcript import adapters;
- live smoke-test hooks.

Adapters produce typed results and evidence. They do not schedule tasks or
write projections directly.

### 2.8 `agent-server`, `agent-cli`, And `apps/lens-web`

The server and CLI call the same service functions and read the same store
projections. The web app consumes API projections only.

Runtime decisions do not live in formatting, HTTP handlers, or React state.

## 3. Canonical Event Contract

The next contract slice should either introduce `agentlens.event.v3` or widen
`agentlens.event.v2` in a backward-compatible way. The contract must support a
common orchestrator envelope:

```json
{
  "schema": "agentlens.event.v3",
  "event_id": "evt_...",
  "agentlens_run_id": "run_...",
  "orchestrator_run_id": "runway_...",
  "producer": {
    "name": "agentrunway",
    "kind": "orchestrator",
    "version": "..."
  },
  "event_type": "agentrunway.task_result",
  "occurred_at": "2026-05-21T00:00:00Z",
  "sequence": 42,
  "phase": "verification",
  "outcome": "success",
  "severity": "info",
  "trust_impact": "supports_success",
  "summary": "Verification passed.",
  "payload": {}
}
```

Required properties:

- `occurred_at` and `sequence` are the canonical ordering pair.
- `agentlens_run_id` and `orchestrator_run_id` are separate.
- `producer.name` identifies `agentrunway`, `waygent`, `codex`,
  `claude`, or `local`.
- `producer.kind` distinguishes `orchestrator`, `worker`, `reviewer`,
  `verifier`, `adapter`, and `importer`.
- `event_type` allows `agentrunway.*` and future
  `waygent.*`.
- old `kws-cpe.*` and `kws-cme.*` are legacy import labels, not accepted new
  runtime namespaces.
- payloads are bounded and redacted before persistence or external emission.

## 4. Typed Core Events

The unified contract needs typed payload schemas for at least these core event
families:

- `run_started`
- `run_finished`
- `task_dispatched`
- `task_result`
- `review_result`
- `verification_result`
- `candidate_ranked`
- `quality_decision`
- `gate_retry`
- `barrier_detected`
- `recovery_action`
- `decision_packet_created`
- `merge_result`
- `apply_result`
- `artifact_ready`
- `observability_degraded`

Opaque extension payloads remain allowed, but core status, task, candidate,
gate, failure, and evidence fields must be typed.

## 5. Durable State And Recovery

The orchestrator state machine should be the only dispatch source:

```text
durable artifacts
  -> state machine
  -> durable projection
  -> next action
  -> adapter / gate / merge / decision
  -> event + artifact + checkpoint
  -> projection refresh
```

The projection owns:

- current run status;
- ready queue;
- safe wave;
- withheld tasks;
- stale activities;
- blocked node;
- failure class;
- next automatic action;
- required human decision;
- latest checkpoint;
- checkpoint repair tasks;
- observability health.

Failure policy must be typed:

| Failure | Policy |
|---|---|
| `needs_rebase` | Retry once; repeated failure blocks. |
| `needs_full_context` | Retry once with expanded context. |
| `needs_plan_fix` | Stop for plan/spec correction. |
| `needs_infra_fix` | Stop as environment/tooling problem. |
| `missing_checkpoint` | Reconstruct only from durable merge evidence. |
| `missing_resume_handler` | Block; never record fake progress. |
| `file_claim_violation` | Reject candidate and redispatch or block by risk. |
| `verification_failed` | Retry once only if actionable. |
| `review_changes_requested` | Retry once with review evidence. |
| `human_decision_required` | Write decision packet and stop. |
| `observability_unavailable` | Degrade trust, but keep local execution evidence authoritative. |
| `unknown` | Block safely. |

## 6. Store And Outbox Ordering

The local journal is authoritative. Event persistence order must be:

1. validate and redact event;
2. append local JSONL event under the run directory;
3. update local SQLite / outbox state;
4. emit to AgentLens or another external sink;
5. update outbox status as emitted, failed, or disabled.

External emission must never create the only copy of an event. If external
emission fails, backfill can replay from `(producer, orchestrator_run_id,
sequence)` or event id.

## 7. Version-Aware Evaluation And API

Evaluator and API layers must normalize versions before projecting:

- v1 `agent_outcome` and v2 `claimed_outcome` become one canonical projected
  outcome.
- v1 `type` / `ts` and v2+ `event_type` / `occurred_at` become one event read
  model.
- evaluation output schema matches the run contract version or explicitly
  records its normalized source version.

The API should add versioned read surfaces:

- `/api/v2/runs`
- `/api/v2/runs/{run_id}/events`
- `/api/v2/runs/{run_id}/projection`
- `/api/v2/runs/{run_id}/trust`
- `/api/v2/runs/{run_id}/observability-health`
- `/api/v2/meta`

Existing `/api/v1` remains compatibility-only.

## 8. Harness Architecture

The new harness must separate deterministic confidence from live-model smoke
coverage.

### 8.1 Deterministic Required Harness

- schema compatibility fixtures for v1, v2, and unified contracts;
- fake adapter end-to-end runs;
- safe-wave and file-claim scheduling tests;
- checkpoint release and missing-checkpoint repair tests;
- failure barrier tests;
- result validation and method-audit tests;
- store replay and SQLite rebuild tests;
- AgentLens-disabled and AgentLens-failed backfill tests;
- CLI/server/web projection parity tests.

### 8.2 Optional Live Harness

Live Codex or Claude runs are opt-in only. They may verify adapter integration,
but they are not the required correctness gate for contract or state-machine
behavior.

## 9. Migration Rules

- Keep current Python AgentLens and AgentRunway code until Rust store, runtime,
  evaluator, CLI, API, and dashboard parity exist.
- Do not delete or move `AgentLens/src`, `AgentLens/tests`, `AgentLens/web/src`,
  or `skills/agent-runway/scripts` in the contract reconciliation slice.
- Treat `kws-cpe.*` and `kws-cme.*` as legacy import namespaces only.
- Do not create new `agent.*` runtime schema names unless they are explicitly
  aliases for canonical `agentlens.*` contracts.
- Keep imported full transcript material behind explicit operator consent and
  synthetic fixtures by default.

## 10. Revised Implementation Order

1. Contract reconciliation spec and plan.
2. Rust workspace skeleton with only `agent-core` and `agent-contracts`.
3. Store compatibility layer and schema-version normalization.
4. Deterministic fake-adapter E2E harness.
5. Orchestrator state machine and durable projection.
6. AgentRunway execution role on the shared orchestrator substrate.
7. Trust evaluator and projection read models.
8. CLI/server/API parity.
9. Dashboard relocation or port.
10. Legacy Python removal after parity.

## 11. Acceptance Criteria For The Next Plan

The next implementation plan must prove:

- no new competing event schema dialect is introduced;
- v1 AgentLens artifacts remain readable;
- AgentRunway v2 evidence remains readable;
- old `kws-cpe.*` and `kws-cme.*` are rejected for new runtime events but can
  be imported as legacy labels;
- local event journal survives AgentLens CLI failure;
- SQLite can be deleted and rebuilt from JSON artifacts;
- evaluator and API normalize run/event/final schema versions;
- fake-adapter E2E covers run start, task dispatch, review, verification,
  merge, checkpoint, final, eval, projection, and trust report.

## 12. Immediate Plan Corrections

Before any Rust implementation begins:

- mark the current Phase 1 skeleton plan as blocked pending this reconciliation;
- update the plan README so current plan authority is not the v0 task file;
- replace `agent.*` schema names in the Phase 1 plan with canonical contract
  names or defer schema file creation until the contract plan defines them;
- add contract reconciliation as Phase 0 before skeleton and crate creation.
