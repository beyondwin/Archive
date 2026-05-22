# Waygent Event Contracts

Related contracts:

- [Run state](./run-state.md)
- [Provider result](./provider-result.md)

Canonical events use `agentlens.event.v3`. The schema name is retained for
durable compatibility and does not require the legacy Python AgentLens runtime.
Product event families are:

- `platform.*`
- `runway.*`
- `kernel.*`
- `lens.*`

Legacy KWS executor namespaces are rejected by the contract validator.
Filesystem JSONL artifacts remain the source of truth. SQLite is a rebuildable
projection cache.

## Runtime Improvement Events

The runtime improvement slice adds these active Waygent events:

- `platform.plan_preflight_completed`: deterministic plan/spec audit result.
- `platform.cost_accumulated`: provider dispatch usage and cost ledger update.
- `platform.cost_budget_warning`: configured warning budget was exceeded.
- `platform.cost_budget_paused`: configured pause budget stopped the next safe
  boundary.
- `runway.decision_appended` and `runway.decision_superseded`: structured
  worker decision was persisted to the run decision register.
- `runway.spec_slice_computed`: task packet spec context was sliced or fell
  back to the full spec.
- `kernel.hook_denied` and `kernel.hook_bypassed`: runtime hook decision at
  pre-dispatch or final-output boundaries.
- `lens.model_attestation_confirmed` and
  `lens.model_attestation_mismatch`: requested and actual provider model
  comparison.
- `lens.evidence_apply_blocked` and `lens.evidence_apply_gated`: opt-in method
  evidence policy at apply time.

Event payloads use `.event_type`; consumers must not query legacy `.type`.

Waygent owns active runtime events. Lens reads those events through
`packages/lens-store` and `packages/lens-projectors`. KWS executor namespaces
are historical and must not be emitted by new Waygent runs. Python AgentLens
schemas and projections are not part of the active event contract.
