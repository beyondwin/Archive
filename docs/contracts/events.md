# Events

Related: [run state](./run-state.md), [provider result](./provider-result.md).

Canonical envelope: `agentlens.event.v3`. The name is for compatibility. It
does not need the old Python runtime.

Families:

- `platform.*`
- `runway.*`
- `kernel.*`
- `lens.*`

JSONL on disk is source of truth. SQLite is a rebuildable cache. Consumers
read `.event_type`, not a legacy `.type`. Treat the family prefix as the
contract and discover specific types from the journal.

Examples from current runs:

- Platform: `platform.run_started`, `platform.plan_preflight_completed`,
  `platform.intake_decision_required`, `platform.budget_paused`
- Runway: `runway.safe_wave_selected`, `runway.verification_result`,
  `runway.checkpoint_created`, `runway.recovery_scheduled`,
  `runway.apply_blocked`, `runway.apply_completed`
- Kernel: `kernel.hook_denied`, `kernel.hook_bypassed`
- Lens: `lens.evidence_apply_blocked`, `lens.model_attestation_mismatch`

Waygent emits runtime events. Lens reads them through `packages/lens-store`
and `packages/lens-projectors`. New runs must not emit KWS executor namespaces.
