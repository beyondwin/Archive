# AgentLens + KWS Common Observability Contract — Design Spec

**Date:** 2026-05-20
**Status:** Draft
**Scope:** AgentLens evaluator coverage, `kws-codex-plan-executor`, `kws-claude-multi-agent-executor`, historical KWS run backfill
**Extends:** `AgentLens/docs/spec/2026-05-19-agentlens-skill-auto-record-design.md`, `AgentLens/docs/plan/2026-05-19-agentlens-v1-and-kws-unification.md`

## 1. Problem

AgentLens now has the right substrate for KWS orchestration runs: container runs,
opaque namespaced events, finalization, importers, schema validation, and an
evaluator. The remaining gap is semantic consistency.

`kws-codex-plan-executor` (CPE) and `kws-claude-multi-agent-executor` (CME)
currently describe related concepts with different event namespaces and payload
shapes:

- CPE documents `kws-cpe.<event>` and `kws-cpe.learning.<event>` events,
  with state centered on `completion_audit`, `verification_evidence`, and
  `lifecycle_outcome`.
- CME documents `kws-cme.<event_type>` events, with state centered on
  `plan_chain`, `context_health`, chained child handoff, and cost/context
  ledgers.

Those executor-specific state models should remain separate. They are the
resume source of truth for different execution engines. But the data emitted to
AgentLens should be common. Otherwise the evaluator, dashboard, and later
analytics need parallel code paths for CPE and CME even when both are reporting
the same concept: task progress, verification evidence, context health,
blockers, residual risk, and terminal outcome.

The current local store also shows why this matters:

- No `kws-cpe.*` or `kws-cme.*` events were present in `~/.agentlens` during
  analysis, even though both skills document AgentLens emission. In this
  environment `agentlens` was not on `PATH`, so observability can silently
  degrade unless the skills record an explicit AgentLens availability status.
- Existing AgentLens evaluator failures are dominated by evidence-linkage gaps
  such as legacy `command.finished` events without `command_hash`.
- Imported session runs can carry very large/raw canonical payloads, so any new
  KWS event contract must be bounded and privacy-conscious by default.

## 2. Goals

- CPE and CME keep separate internal state and execution procedures.
- CPE and CME emit the same versioned AgentLens payload contract.
- AgentLens consumes the common contract without special-casing CPE vs CME.
- Existing `kws-cpe.*` and `kws-cme.*` events remain readable for historical
  runs.
- AgentLens evaluator gains an explanatory `evidence_coverage` block without
  changing the authoritative `status` semantics.
- KWS runs surface when AgentLens observability is disabled instead of silently
  losing events.
- Historical CPE/CME state can be backfilled through an explicit importer.

## 3. Non-Goals

- Replacing CPE/CME `state.json` with AgentLens events.
- Making AgentLens crawl arbitrary KWS state directories by default.
- Storing raw prompts, full transcripts, long command logs, or absolute home
  paths inside KWS event payloads.
- Rewriting historical `kws-cpe.*` / `kws-cme.*` event files in place.
- Building dashboard UI in the first implementation PR.

## 4. Architecture

The system has three layers:

```text
KWS executor state          AgentLens event store          AgentLens evaluator
------------------          ---------------------          -------------------
CPE state.json       --->   run.json                 --->  eval.json
CME state.json       --->   events.jsonl             --->  evidence_coverage
verification data    --->   final.json               --->  failure taxonomy
context health       --->   manifest.json
```

CPE/CME are evidence producers. AgentLens is the durable recorder and evaluator.
The source-of-truth boundary is explicit:

- CPE/CME state controls resume, task scheduling, handoff, and local execution.
- AgentLens stores bounded observations about those runs.
- Evaluator checks AgentLens observations after the fact.
- A missing or failed AgentLens write never blocks KWS execution.

## 5. Common Event Namespace

New KWS observability events use the shared namespace:

```text
kws.orchestrator.run_started
kws.orchestrator.context_health
kws.orchestrator.task_started
kws.orchestrator.task_finished
kws.orchestrator.verification_evidence
kws.orchestrator.blocker
kws.orchestrator.run_finished
```

The producer is identified inside the payload:

```json
{
  "schema": "kws.orchestrator.event.v1",
  "producer": "kws-cpe",
  "producer_run_id": "cpe-run-id",
  "phase": "verification",
  "event_name": "verification_evidence",
  "task_id": "task_3",
  "outcome": "success",
  "severity": "info",
  "evidence": {
    "kind": "test",
    "command_hash": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "status": "passed",
    "artifact_ref": "state:verification_evidence[2]"
  },
  "context": {
    "health": "green",
    "handoff_ready": true,
    "residual_risk_count": 0
  }
}
```

`event.type` says what kind of observation this is. `payload.producer` says
which executor produced it. This prevents namespace explosion and lets
AgentLens query both executors with a single event-type filter.

## 6. Payload Contract

All `kws.orchestrator.*` payloads share this envelope:

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `schema` | string const | yes | `kws.orchestrator.event.v1` |
| `producer` | enum | yes | `kws-cpe`, `kws-cme` |
| `producer_run_id` | string | yes | Native CPE/CME run id, not AgentLens run id |
| `phase` | enum | yes | `setup`, `execution`, `verification`, `handoff`, `final` |
| `event_name` | string | yes | Last segment of the AgentLens event type |
| `task_id` | string/null | yes | Native task id when applicable |
| `outcome` | enum | yes | `success`, `failed`, `partial`, `cancelled`, `unknown` |
| `severity` | enum | yes | `info`, `warn`, `error` |
| `evidence` | object/null | yes | Bounded evidence reference |
| `context` | object/null | yes | Bounded context-health and risk summary |

Allowed evidence fields:

| Field | Type | Meaning |
|---|---|---|
| `kind` | enum | `test`, `lint`, `typecheck`, `review`, `manual`, `state_check`, `command` |
| `command_hash` | string/null | AgentLens command hash when linkable |
| `status` | enum | `passed`, `failed`, `skipped` |
| `artifact_ref` | string/null | Redacted reference to state/artifact evidence |
| `summary` | string/null | Human summary, capped at 512 chars |

Allowed context fields:

| Field | Type | Meaning |
|---|---|---|
| `health` | enum/null | `green`, `yellow`, `red` |
| `handoff_ready` | boolean/null | Whether the run can be resumed safely |
| `residual_risk_count` | integer | Count only, not full raw risk text |
| `medium_plus_residual_risk_count` | integer | Count of medium/high/critical risks |
| `changed_files_count` | integer/null | Count only |
| `context_snapshot_ref` | string/null | Redacted artifact/state reference |

All string summaries are capped. Absolute home paths, secrets, raw prompts,
raw transcript lines, and long logs are forbidden.

The locked `agentlens.event.v1` schema still treats non-core `payload` as an
opaque JSON object. The common KWS envelope is therefore enforced in two places:
the KWS emit helper before writing, and the AgentLens coverage/evaluator module
when reading. It is not added as a nested JSON Schema constraint inside
`event.schema.json`.

## 7. Outcome Mapping

AgentLens already accepts these final outcomes:

```text
success | failed | partial | cancelled | unknown
```

KWS executors map local lifecycle values before emitting `run_finished` or
calling `agentlens run-close`:

| Local value | AgentLens outcome |
|---|---|
| CPE `finished` | `success` |
| CPE `blocked` | `partial` |
| CPE `failed` | `failed` |
| CPE `cancelled` | `cancelled` |
| CME `success` | `success` |
| CME `blocked` | `partial` |
| CME `aborted` | `cancelled` |
| unknown/missing | `unknown` |

This removes the current mismatch where CME prose references `blocked` and
`aborted`, while AgentLens `final.json` only accepts the AgentLens outcome set.

## 8. KWS Skill Changes

### 8.1 Shared emit helper contract

Both skills get the same logical helper contract, even if implemented inline at
first:

```text
emit_kws_event(event_name, phase, task_id, outcome, severity, evidence, context)
```

The helper:

1. Reads the current AgentLens run id from `ORCH_RUN_ID` or state.
2. Returns immediately if no run id is available.
3. Builds the `kws.orchestrator.event.v1` envelope.
4. Emits to `agentlens event append --type "kws.orchestrator.<event_name>"`.
5. Records best-effort counters in state: `last_agentlens_event_at` and
   `emitted_event_count`.
6. Never blocks execution on AgentLens failure.

### 8.2 AgentLens status in state

Both skills record:

```json
{
  "agentlens_orchestration_run": "run_...",
  "agentlens_status": "active",
  "last_agentlens_event_at": "2026-05-20T00:00:00Z",
  "emitted_event_count": 12
}
```

Allowed `agentlens_status` values:

```text
active | unavailable | error
```

If `agentlens run-open` fails or the CLI is absent, state records
`agentlens_status="unavailable"` and the final summary mentions that AgentLens
observability was disabled for the run.

### 8.3 Backward compatibility

Existing `kws-cpe.*` and `kws-cme.*` events remain historical data. New code
emits only `kws.orchestrator.*` after cutover. AgentLens coverage scoring reads:

1. `kws.orchestrator.*` first.
2. Legacy `kws-cpe.*` / `kws-cme.*` as fallback where mappable.
3. No KWS evidence if neither exists.

## 9. AgentLens Evaluator Changes

`eval.json` gains an optional additive field:

```json
{
  "evidence_coverage": {
    "command_linkage": "full",
    "verification_strength": "test_backed",
    "manifest_integrity": "sealed",
    "import_completeness": "not_imported",
    "canonical_payload_safety": "ok",
    "kws_observability": "present"
  }
}
```

The authoritative status rules do not change:

- `status="passed"` still means all required checks passed.
- `status="failed"` still means at least one required check failed.
- `evidence_coverage` explains evidence quality and weak spots.

Coverage dimensions:

| Dimension | Values |
|---|---|
| `command_linkage` | `full`, `legacy_hashless`, `missing_finished`, `none` |
| `verification_strength` | `test_backed`, `direct_command`, `manual`, `weak`, `none` |
| `manifest_integrity` | `sealed`, `missing`, `mismatch` |
| `import_completeness` | `not_imported`, `full`, `partial`, `unfinalized` |
| `canonical_payload_safety` | `ok`, `oversized`, `raw_context_detected` |
| `kws_observability` | `present`, `legacy_only`, `backfilled`, `missing`, `disabled` |

`kws_observability="disabled"` is derived when KWS state or imported KWS
summary says AgentLens was unavailable. `missing` means the run looks like KWS
but has no KWS semantic evidence.

## 10. Backfill Importer

Push events are the primary path for live runs. AgentLens should also provide
an explicit importer for historical or missed KWS runs:

```bash
agentlens import kws-orchestrator --kind cpe --run-dir ~/.codex/orchestrator/<run_id>
agentlens import kws-orchestrator --kind cme --run-dir ~/.claude/orchestrator/<run_id>
```

The importer:

- Reads KWS `state.json` and known bounded artifacts.
- Creates or updates an AgentLens container run.
- Emits `kws.orchestrator.*` events reconstructed from state.
- Marks `kws_observability` as `backfilled`.
- Writes an `artifacts/import_report.json` with counts and skipped fields.

The importer does not copy raw headless logs or transcripts. It uses refs,
counts, hashes, and short summaries only.

## 11. Privacy and Payload Safety

The common contract uses allow-listed fields. Anything outside the envelope is
rejected by the KWS helper before `agentlens event append`.

Hard limits:

- `evidence.summary`: 512 chars.
- `context.context_snapshot_ref`: redacted or home-relative only.
- No raw prompt.
- No raw transcript.
- No long command output.
- No absolute `$HOME` paths.
- No secrets.

AgentLens evaluator also scans canonical event payloads for oversized payloads
and obvious raw-context markers. That catches importer or legacy event paths
that bypass the KWS helper.

## 12. Testing Strategy

### AgentLens tests

- Schema fixture for valid `kws.orchestrator.verification_evidence`.
- Unit test for invalid common-envelope payloads in the KWS helper or
  AgentLens coverage parser.
- Evaluator fixture: success with test-backed KWS evidence.
- Evaluator fixture: success without verification evidence.
- Evaluator fixture: legacy `command.finished` without `command_hash`.
- Evaluator fixture: imported transcript with unfinalized state.
- Evaluator fixture: oversized/raw canonical payload.
- KWS importer fixture for CPE state.
- KWS importer fixture for CME state.

### KWS skill tests

- CPE emits the common envelope for verification evidence.
- CME drains candidate JSON into the common envelope.
- Outcome mappings produce AgentLens-allowed outcomes.
- `agentlens_status` becomes `unavailable` when `agentlens` is absent.
- Payload helper rejects absolute home paths and oversized summaries.

## 13. Rollout Plan

1. Add AgentLens coverage module and optional `evidence_coverage` schema field.
2. Add fixtures for coverage and KWS common events.
3. Add shared KWS event contract docs and payload helper rules.
4. Update CPE emit sites to `kws.orchestrator.*`.
5. Update CME candidate-drain and direct emit sites to `kws.orchestrator.*`.
6. Normalize run-close outcome mapping.
7. Add `agentlens_status` and emission counters to both states.
8. Add `agentlens import kws-orchestrator` for backfill.
9. Teach evaluator to consume common KWS events.
10. Add dashboard projection later.

The first implementation PR should stop after steps 1-3 if necessary. It is
better to lock the contract and fixtures before changing both skills.

## 14. Design Decisions

### Decision 1: Event namespace

Use `kws.orchestrator.*` instead of `kws-cpe.*` and `kws-cme.*`.

Reason: the producer belongs in payload, not in event type. This gives
AgentLens one query surface and makes future executors additive.

### Decision 2: Internal state

Do not unify CPE and CME state.

Reason: their execution engines differ. Common state would either erase useful
executor-specific details or become a leaky union type. The stable boundary is
the emitted evidence contract.

### Decision 3: Pull vs push

Use push for live runs and explicit import for backfill.

Reason: AgentLens cannot infer KWS semantic data reliably from process traces.
It can observe command execution, but CPE/CME know which commands are
verification, which risks remain, and why a run is blocked.

## 15. Acceptance Criteria

- New CPE and CME runs emit at least one `kws.orchestrator.run_started` and one
  terminal `kws.orchestrator.run_finished` event when AgentLens is available.
- Verification events from both executors validate against the same envelope.
- AgentLens evaluator writes `evidence_coverage` without changing existing
  required `eval.json` fields.
- CME `aborted` no longer reaches `agentlens run-close`; it maps to
  `cancelled`.
- KWS runs with AgentLens unavailable record `agentlens_status="unavailable"`.
- No new payload stores raw prompts, transcripts, long logs, secrets, or
  absolute home paths.
