Source-of-truth: the design document wins when this reference and code disagree.

# AgentLens Events

AgentRunway records runner-validated facts locally before attempting best-effort
AgentLens emission. The local journal is `events.jsonl` in the run directory.
SQLite table `agentlens_events` is the outbox and stores one of:

- `agentlens_disabled` (no emitter configured; event is local-only)
- `agentlens_emitted` (emit attempt returned without raising)
- `agentlens_failed` (emit attempt raised; `error` column records the reason)

The local journal write always succeeds before the emit attempt, so every
status implies a durable `events.jsonl` row and a matching
`agentlens_events` row.

Core event types:

- `agentrunway.run_started`
- `agentrunway.contract_created`
- `agentrunway.worker_dispatched`
- `agentrunway.worker_result`
- `agentrunway.worker_rejected`
- `agentrunway.review_dispatched`
- `agentrunway.review_result`
- `agentrunway.verification_dispatched`
- `agentrunway.verification_result`
- `agentrunway.gate_retry`
- `agentrunway.merge_ready`
- `agentrunway.merge_applied`
- `agentrunway.merge_conflict`
- `agentrunway.resume_planned`
- `agentrunway.resume_action`
- `agentrunway.apply_started`
- `agentrunway.apply_finished`
- `agentrunway.run_finished`
- `agentrunway.run_blocked`

Payload redaction happens before local write and before AgentLens emission. Home
paths become `~`; secret-like keys such as `token`, `api_key`, `secret`, and
`password` become `[REDACTED]`. Payloads are bounded before local write and
before AgentLens emission; oversized extras are replaced with truncation
markers while preserving run id, phase, outcome, severity, summary, and privacy
metadata.

Local event payloads still include `schema="agentrunway.event.v1"` for runner
state compatibility, but `events.jsonl` now stores an `agentlens.event.v2`
envelope with `event_type`, `occurred_at`, `sequence`, `phase`, `outcome`,
`severity`, `trust_impact`, evidence refs, artifact refs, and the bounded
payload. When an AgentLens container run is open, external emission sends that
raw v2 envelope to `agentlens event append`; the envelope `run_id` is rewritten
to the AgentLens run id while the nested payload preserves
`agentrunway_run_id`. AgentLens emission is best effort; failed emission must
not stop plan execution.

## Quality Decision Events

AgentRunway emits decision events when policy or candidate ranking changes the
execution path:

- `agentrunway.quality_decision`: retry, block, continue, or manual-action decisions.
- `agentrunway.candidate_ranked`: deterministic candidate score table and selected candidate.
- `agentrunway.conflict_redispatch_planned`: first merge conflict converted into a safe redispatch plan.

These events are explanatory evidence. AgentRunway SQLite state remains the
source of truth for task, worker, and merge status.
