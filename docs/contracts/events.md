# Events

Related: [run file](./run-state.md), [provider result](./provider-result.md).

Event wrapper: `agentlens.event.v3`. The name is for compatibility. It
does not need the old Python runtime.

Families:

- `platform.*`
- `runway.*`
- `kernel.*`
- `lens.*`

JSONL on disk is the saved record. SQLite is a cache you can rebuild. Readers
use `.event_type`, not a leftover `.type`. Treat the family prefix as the
contract and discover specific types from the log.

Examples from current runs:

- Platform: `platform.run_started`, `platform.plan_preflight_completed`,
  `platform.intake_decision_required`, `platform.budget_paused`
- Runway: `runway.safe_wave_selected`, `runway.verification_result`,
  `runway.checkpoint_created`, `runway.recovery_scheduled`,
  `runway.apply_blocked`, `runway.apply_completed`
- Kernel: `kernel.hook_denied`, `kernel.hook_bypassed`
- Lens: `lens.evidence_apply_blocked`, `lens.model_attestation_mismatch`

Waygent writes runtime events. Lens reads them through `packages/lens-store`
and `packages/lens-projectors`. New runs must not emit KWS executor names.
