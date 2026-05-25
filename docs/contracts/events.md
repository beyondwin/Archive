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

## Event Families

The `platform.*`, `runway.*`, `kernel.*`, and `lens.*` family prefixes are the
authoritative boundary. Active event types within each family evolve with the
runtime; the JSONL journal and the orchestrator emitter are the source of
truth for the current set.

Representative events seen in current runs include:

- Platform: `platform.run_started`, `platform.plan_preflight_completed`,
  `platform.intake_extract_completed`, `platform.intake_decision_required`,
  `platform.cost_accumulated`, `platform.cost_budget_warning`,
  `platform.cost_budget_paused`, `platform.provider_capability_attested`.
- Runway: `runway.plan_loaded`, `runway.preflight_result`,
  `runway.execution_profile_selected`, `runway.safe_wave_selected`,
  `runway.wave_barrier_inserted`, `runway.diff_scope_result`,
  `runway.verification_environment`, `runway.verification_result`,
  `runway.checkpoint_created`, `runway.recovery_scheduled`,
  `runway.recovery_decision_required`, `runway.apply_blocked`,
  `runway.apply_completed`, `runway.decision_appended`,
  `runway.decision_superseded`, `runway.spec_slice_computed`.
- Kernel: `kernel.hook_denied`, `kernel.hook_bypassed`, and other
  kernel-boundary decisions.
- Lens: `lens.model_attestation_confirmed`, `lens.model_attestation_mismatch`,
  `lens.evidence_apply_blocked`, `lens.evidence_apply_gated`.

Consumers should treat the family prefix as the contract and discover specific
event types from the journal rather than relying on a frozen list here.

Event payloads use `.event_type`; consumers must not query legacy `.type`.

Waygent owns active runtime events. Lens reads those events through
`packages/lens-store` and `packages/lens-projectors`. KWS executor namespaces
are historical and must not be emitted by new Waygent runs. Python AgentLens
schemas and projections are not part of the active event contract.
