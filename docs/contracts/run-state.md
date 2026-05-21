# Waygent Run State Contract

## Source Of Truth

`waygent.run_state.v2` is the authoritative runtime state for task status,
provider attempts, verification evidence, review records, recovery decisions,
drift, completion audit, and apply readiness.

AgentLens events and API or console projections can replay or present that
evidence, but they do not replace the run state contract.

## Task State

Task state records pending, running, verified, failed, blocked, and completed
work with task ids, candidate ids, file claims, provider attempts, verification
evidence, and review records.

## Safe Waves

Safe waves describe which tasks can run together. The scheduler must respect
dependencies, file claims, risk, and checkpoint requirements before releasing a
task.

## Checkpoints

Checkpoint refs point to manifest-backed artifacts, patch bytes, digest and
length evidence, and dry-run verification results. Empty patches are valid only
when represented as explicit no-op checkpoint evidence.

## Completion Audit

Completion audit verifies that task outcomes, provider evidence, checkpoints,
review records, and runtime status agree before a run can be considered
complete.

## Reconciliation

Reconciliation detects missing artifacts, digest mismatches, source drift,
checkpoint drift, and other blockers that can invalidate apply readiness.

## Apply Readiness

Apply readiness is `ready`, `not_ready`, `blocked`, or `applied`. `ready`
requires verified checkpoints, valid combined patch evidence, passed dry-run
checks, clean source checkout, no unrepaired drift, and a passed completion
audit.

## Related Tests

Inspect `tests/fixtures/contracts/valid-run-state-v2.json` for the fixture
shape. Runtime behavior is covered by `packages/orchestrator/tests/runStateV2.test.ts`,
`packages/orchestrator/tests/orchestratorRunV2.test.ts`,
`packages/orchestrator/tests/applyEngine.test.ts`, and
`packages/lens-projectors/tests/apply.test.ts`.
