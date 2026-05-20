# Design: AgentLens AgentRunway Trust Console

Date: 2026-05-21
Status: Approved for implementation planning
Owner: KWS

## 1. Summary

AgentLens will become a first-class trust console for AgentRunway execution.
AgentRunway remains the only supported execution orchestrator connected to
AgentLens. AgentLens records, projects, and evaluates runner-validated
AgentRunway evidence so operators can answer one question quickly:

```text
Can this AgentRunway run be trusted, and what evidence supports that verdict?
```

This design intentionally drops legacy compatibility as a constraint. AgentLens
does not preserve the v1 schema contract for this slice, does not support
CPE/CME namespaces, and does not introduce a bridge for old KWS executor event
families. The optimized target is:

- AgentRunway emits structured `agentrunway.*` events with typed evidence
  references.
- AgentLens stores the events under a new v2 run contract.
- AgentLens materializes a deterministic AgentRunway projection.
- AgentLens materializes a trust report that separates claimed outcome from
  evidence-backed verdict.
- CLI and dashboard surfaces use the same trust report.

AgentLens stays downstream. AgentRunway local state remains the source of truth
for execution, scheduling, recovery, apply, and cleanup.

## 2. Context

The Archive repository has moved away from the older KWS Codex Plan Executor
and KWS Claude Multi Agent Executor split. Current planning makes
`skills/agent-runway/` the only supported plan-execution skill connected to
AgentLens. Existing AgentLens docs also describe a locked v1 storage contract,
generic dotted event namespaces, additive compatibility rules, importers, and a
dashboard.

Those v1 compatibility constraints are not carried forward here. The user
explicitly approved a no-legacy direction: do not support legacy schemas, do
not keep CPE/CME compatibility, and change the schema to the best shape for the
new AgentRunway trust model.

## 3. Goals

- Make AgentLens a trust and evidence layer for AgentRunway runs.
- Promote `agentrunway.*` from generic external events to a first-class
  AgentLens event family.
- Replace the v1 compatibility-first contract with AgentLens v2 artifacts tuned
  for AgentRunway trust evaluation.
- Make false success, missing verification, weak retry evidence, missing blocked
  reasons, and projection drift explicit.
- Keep AgentRunway execution non-blocking when AgentLens is disabled,
  unavailable, or unable to write.
- Show the same trust report in CLI and dashboard.
- Keep CPE/CME/KWS legacy namespaces unsupported.

## 4. Non-Goals

- No support for `kws-cpe.*`, `kws-cme.*`, or `kws.orchestrator.*`.
- No migration bridge from AgentLens v1 runs into the v2 trust contract.
- No runtime fallback parser for old event shapes.
- No attempt to make AgentLens the AgentRunway execution source of truth.
- No AgentLens write path from workers. Only the AgentRunway runner emits facts.
- No raw transcript viewer work in this slice.
- No broad multi-agent control center. AgentLens stays read-only for
  AgentRunway operations.

## 5. Architecture

The architecture has one execution source and one trust projection layer:

```text
approved spec/plan
  -> AgentRunway
     -> SQLite state
     -> contract.json
     -> events.jsonl
     -> artifact_graph.json
     -> coverage.json
     -> runner-validated agentrunway.* events
  -> AgentLens v2
     -> run/event/final/manifest artifacts
     -> agentrunway_projection.json
     -> trust_report.json
     -> CLI and dashboard trust views
```

AgentRunway owns scheduling, worker dispatch, review, verification, merge,
resume, apply, cleanup, and durable local state. AgentLens consumes only facts
that AgentRunway accepted or validated. Worker-claimed status, free-form worker
text, and unverified artifacts do not become trusted evidence until the runner
turns them into structured events.

AgentLens evaluates the evidence chain after the fact. It can say a run is
trustworthy, partially trustworthy, untrusted, or degraded, but that verdict
does not mutate AgentRunway's state machine.

## 6. Schema Direction

AgentLens gets a new optimized contract for this direction:

```text
agentlens.run.v2
agentlens.event.v2
agentlens.final.v2
agentlens.eval.v2
agentlens.manifest.v2
agentlens.agentrunway_projection.v1
agentlens.trust_report.v1
```

The v2 run contract is not an additive extension of v1. It is a new runtime
shape. Existing v1 runs can remain on disk as historical data, but the Trust
Console implementation does not need to read them, migrate them, or preserve
their query behavior.

The `v1` suffix on `agentlens.agentrunway_projection.v1` and
`agentlens.trust_report.v1` means "first version of these new derived
artifacts." It does not imply compatibility with the old AgentLens v1 runtime
contract.

### 6.1 Event Envelope

Every `agentlens.event.v2` row has a common envelope:

```json
{
  "schema": "agentlens.event.v2",
  "event_id": "evt_...",
  "run_id": "run_...",
  "event_type": "agentrunway.verification_result",
  "producer": {
    "name": "agentrunway",
    "version": "..."
  },
  "occurred_at": "2026-05-21T00:00:00Z",
  "sequence": 1,
  "phase": "verification",
  "outcome": "success",
  "severity": "info",
  "task_id": "task_001",
  "attempt_id": "attempt_001",
  "evidence_refs": [],
  "artifact_refs": [],
  "trust_impact": "supports_success",
  "summary": "Verification passed.",
  "payload": {}
}
```

Required common fields:

- `event_id`
- `run_id`
- `event_type`
- `producer`
- `occurred_at`
- `sequence`
- `phase`
- `outcome`
- `severity`
- `trust_impact`
- `summary`
- `payload`

Optional common fields:

- `task_id`
- `attempt_id`
- `candidate_id`
- `gate_id`
- `evidence_refs`
- `artifact_refs`
- `projection_hints`

`payload` remains event-specific, but it is not an unbounded free-form dumping
ground. Each first-class AgentRunway event type defines required payload fields.

### 6.2 First-Class AgentRunway Events

Core events:

```text
agentrunway.run_started
agentrunway.contract_created
agentrunway.worker_dispatched
agentrunway.worker_result
agentrunway.worker_rejected
agentrunway.review_dispatched
agentrunway.review_result
agentrunway.verification_dispatched
agentrunway.verification_result
agentrunway.gate_retry
agentrunway.quality_decision
agentrunway.candidate_ranked
agentrunway.merge_ready
agentrunway.merge_applied
agentrunway.merge_conflict
agentrunway.resume_planned
agentrunway.resume_action
agentrunway.apply_started
agentrunway.apply_finished
agentrunway.run_blocked
agentrunway.run_finished
```

Unsupported event families:

```text
kws-cpe.*
kws-cme.*
kws.orchestrator.*
```

These strings should fail active schema, fixture, and guard checks. They are not
accepted as legacy aliases.

### 6.3 Projection Artifact

`agentlens.agentrunway_projection.v1` is a deterministic derived artifact. It
can be regenerated from `events.jsonl` and is safe to delete and rebuild.

It contains:

- run lifecycle status
- task lifecycle status
- worker attempts per task
- reviewer and verifier gate results
- retry and quality-decision history
- candidate ranking and selected candidate
- merge readiness and merge conflicts
- blocked reasons and required operator actions
- artifact and coverage references
- projection issues for missing, duplicated, or contradictory evidence
- AgentLens observability health

Projection issues are data, not crashes. A malformed run still gets a
projection with explicit gaps.

### 6.4 Trust Report Artifact

`agentlens.trust_report.v1` is the operator-facing verdict:

```json
{
  "schema": "agentlens.trust_report.v1",
  "run_id": "run_...",
  "claimed_outcome": "success",
  "trust_verdict": "untrusted",
  "evidence_strength": "weak",
  "blocking_evidence": [],
  "missing_evidence": [
    {
      "code": "missing_verification_pass",
      "summary": "Run claimed success without a passing verification result."
    }
  ],
  "residual_risks": [],
  "operator_actions": [],
  "projection_issues": []
}
```

Suggested verdict values:

- `trusted`
- `partially_trusted`
- `untrusted`
- `blocked`
- `degraded`

Suggested evidence strength values:

- `strong`
- `adequate`
- `weak`
- `insufficient`

## 7. Components

### 7.1 AgentRunway Event Emitter

AgentRunway writes local state and local event journal first. AgentLens emission
is best effort. The emitter maps runner-validated facts into the v2 event
envelope and rejects or truncates unsafe payloads before writing.

### 7.2 AgentRunway Event Normalizer

The normalizer validates `agentrunway.*` event types, common envelope fields,
event-specific payload fields, redaction state, and payload bounds. It emits
structured normalization issues instead of losing the run.

### 7.3 AgentRunway Projection Builder

The projection builder reads normalized events and produces
`agentrunway_projection.json`. It orders events by sequence and timestamp,
groups them by task, attempt, candidate, and gate, and records contradictions
as projection issues.

### 7.4 Trust Evaluator

The evaluator consumes the projection and produces `trust_report.json`.
Examples:

- `run_finished success` plus passing verification and complete coverage
  produces `trusted`.
- `run_finished success` without passing verification produces `untrusted`.
- review or verification failure followed by retry without linked retry
  evidence produces `partially_trusted` or `untrusted`, depending on outcome.
- `run_blocked` without a blocked reason produces `blocked` with missing
  operator-action evidence.
- oversized or truncated evidence downgrades evidence strength.

### 7.5 CLI Projection Surface

AgentLens CLI shows trust before transcript-like timeline details:

```bash
agentlens show --latest
agentlens show <run_id> --format json
agentlens failures --since-days 30
agentlens risks --since-days 30
agentlens agentrunway <run_id> --format json
```

The exact command set can be narrowed in the implementation plan, but all CLI
paths must use the same trust report artifact.

### 7.6 Dashboard Trust View

The dashboard run detail page leads with:

- claimed outcome
- trust verdict
- evidence strength
- blocking evidence
- missing evidence
- operator actions
- projection issues
- task and gate timeline

The transcript or raw event timeline is secondary. False-success runs must be
distinguishable in the run list.

## 8. Data Flow

### 8.1 Run Start

1. AgentRunway resolves the plan/spec inputs.
2. AgentRunway creates local durable state.
3. AgentRunway opens an AgentLens v2 run when AgentLens is available.
4. AgentRunway emits `agentrunway.run_started` and
   `agentrunway.contract_created`.

### 8.2 Worker and Gate Flow

1. AgentRunway dispatches a worker and emits `worker_dispatched`.
2. AgentRunway validates worker output, changed files, task claims, and
   artifact references.
3. AgentRunway emits `worker_result` or `worker_rejected`.
4. AgentRunway dispatches and records review and verification gates.
5. AgentRunway emits retries, quality decisions, and candidate ranking when
   policy changes the execution path.

### 8.3 Finish and Projection

1. AgentRunway emits merge, blocked, apply, and final events.
2. AgentLens normalizes events.
3. AgentLens builds the AgentRunway projection.
4. AgentLens builds the trust report.
5. CLI and dashboard read the trust report.

## 9. Error Handling

- AgentLens unavailable: AgentRunway continues and records local degraded
  observability.
- AgentLens write failure: AgentRunway continues; AgentLens later reports
  observability degradation if events are incomplete.
- Missing event: projection records `missing_evidence`.
- Duplicate event: projection records a duplicate issue and keeps deterministic
  ordering.
- Contradictory event: projection records `projection_drift` or a more specific
  contradiction code.
- Oversized payload: payload is bounded or rejected; trust strength is
  downgraded when evidence is incomplete.
- `run_finished success` without verification pass: trust report returns an
  untrusted or false-success verdict.
- `run_blocked` without reason: trust report returns blocked with missing
  operator-action evidence.
- AgentRunway state and AgentLens projection disagree: AgentRunway remains the
  source of truth; AgentLens marks projection drift and lowers trust.

## 10. Testing Strategy

### 10.1 Schema Contract Tests

- Add v2 fixtures for `run`, `event`, `final`, `eval`, and `manifest`.
- Add fixtures for `agentrunway_projection.v1` and `trust_report.v1`.
- Require first-class AgentRunway events to pass type-specific validation.
- Reject `kws-cpe.*`, `kws-cme.*`, and `kws.orchestrator.*` active fixtures.

### 10.2 Projection Determinism Tests

- Same events produce byte-stable projection output.
- Event ordering is stable across timestamp and sequence ties.
- Missing, duplicated, and contradictory events produce explicit
  `projection_issues`.
- Projection generation never mutates source events.

### 10.3 Trust Evaluation Tests

- Success with verifier pass and complete artifact coverage is trusted.
- Success without verifier pass is false success.
- Failed gate followed by retry without linked retry evidence is weak recovery
  evidence.
- Blocked run without blocked reason is missing operator-action evidence.
- Truncated or oversized payload downgrades evidence strength.

### 10.4 AgentRunway Integration Tests

- AgentRunway fake run emits v2-compatible `agentrunway.*` events.
- AgentLens disabled or unavailable does not stop AgentRunway execution.
- AgentLens can regenerate trust report from received events.
- Projection drift is reported when AgentRunway local state and AgentLens
  evidence disagree.

### 10.5 CLI and Dashboard Tests

- CLI exposes `claimed_outcome`, `trust_verdict`, `evidence_strength`,
  `blocking_evidence`, and `missing_evidence`.
- Dashboard run list highlights false-success and untrusted runs.
- Dashboard run detail leads with trust report before raw timeline.
- CLI and dashboard snapshots read from the same trust report shape.

## 11. Acceptance Criteria

- AgentLens v2 schema is defined for the AgentRunway Trust Console.
- CPE/CME/KWS legacy namespaces are unsupported and guarded against.
- `agentrunway.*` is a first-class schema event family.
- AgentRunway emits runner-validated v2 event envelopes.
- AgentLens produces deterministic `agentrunway_projection.json`.
- AgentLens produces deterministic `trust_report.json`.
- False success, missing verification, weak retry evidence, missing blocked
  reason, oversized payload, and projection drift are tested.
- CLI and dashboard use the same trust report.
- AgentRunway continues when AgentLens is unavailable.
- Active docs identify AgentRunway as the only execution source and AgentLens as
  the downstream trust layer.

## 12. Rollout Plan

1. Freeze this design as the source of truth.
2. Write an implementation plan that supersedes v1 compatibility assumptions for
   the AgentRunway Trust Console slice.
3. Define the v2 schemas and trust/projection artifact schemas.
4. Add schema rejection guards for CPE/CME/KWS legacy namespaces.
5. Update AgentRunway event emission to the v2 envelope.
6. Implement normalizer, projection builder, and trust evaluator.
7. Wire CLI output to trust report.
8. Wire dashboard run list and detail to trust report.
9. Run schema, projection, trust, AgentRunway integration, CLI, and dashboard
   tests.
10. Update docs and generated graph after code changes.

## 13. References

- `docs/superpowers/specs/2026-05-21-agentrunway-only-cpe-cme-removal-design.md`
- `docs/superpowers/specs/2026-05-20-agentrunway-agentlens-control-plane-design.md`
- `skills/agent-runway/references/agentlens-events.md`
- `AgentLens/docs/contract.md`
- `AgentLens/docs/dashboard.md`
- `AgentLens/docs/adr/2026-05-19-agentlens-ecosystem-benchmark.md`
