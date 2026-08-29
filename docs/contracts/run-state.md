# Run state

`waygent.run_state.v2` is the runtime source of truth: task status, provider
attempts, verification, review, recovery, drift, completion audit, and apply
readiness.

Events, API, and console can replay that evidence. They do not replace it.

## Tasks

Pending, running, verified, failed, blocked, completed. Each task keeps ids,
file claims, provider attempts, verification evidence, and review records.

Additive fields you may also see:

- `evidence_policy` — opt-in method-evidence result
- `hook_retries` — hook denials
- `model_used` — provider attestation when present

## Task packets

- `plan_excerpt` — plan body for this task
- `spec_excerpt` — spec slice or full-spec fallback
- `allowed_exec_commands` — verify commands the sandbox should allow, or
  `null` when the workspace is unknown

## Waves and checkpoints

Waves respect dependencies, file claims, risk, and checkpoints. Checkpoint
refs point at manifests, patch bytes, digest/length, and dry-run results.
Empty patches are valid only as explicit no-op evidence.

## Completion, reconciliation, apply

Completion audit checks that outcomes, evidence, checkpoints, and status
agree. Reconciliation looks for missing artifacts, digest mismatches, and
source drift.

Apply is `ready`, `not_ready`, `blocked`, or `applied`. `ready` needs verified
checkpoints, combined patch evidence, passed dry-run, clean source, no
unrepaired drift, and a passed completion audit.

## Other v2 fields

- `decisions_register`
- `spec_manifest`
- `cost_ledger`
- `budget_cap_usd` / `budget_action`
- `method_evidence_required`
- `hook_config` (`off`, `builtin`, or a path)
- `intake_recovery`

Provider attempts may include `requested_model`, `actual_model`, `usage`, and
`usage_source`. Missing usage is `usage: null` with `usage_source: "unknown"`.

Shape: `tests/fixtures/contracts/valid-run-state-v2.json`. Tests live under
`packages/orchestrator/tests/` and `packages/lens-projectors/tests/apply.test.ts`.
