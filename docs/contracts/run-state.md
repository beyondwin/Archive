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

Task state may also include additive runtime-improvement fields:

- `evidence_policy`: opt-in apply method-evidence policy result.
- `hook_retries`: runtime hook denial count for the task.
- `model_used`: provider-backed model attestations when available.

## Task Packet Fields

Task packets dispatched to providers may carry:

- `plan_excerpt`: deterministic excerpt of the plan body for the task (D-06).
- `spec_excerpt`: spec-slice manifest entry or full-spec fallback content.
- `allowed_exec_commands`: array of shell commands the worker sandbox should
  permit, derived from the task's declared `verification_commands` and the
  current workspace's project-script catalog. Null when the workspace is not
  known to the orchestrator.

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

## Runtime Improvement Fields

`waygent.run_state.v2` remains the schema boundary. Runtime improvements are
additive:

- `decisions_register`: structured decisions copied from
  `worker.evidence.key_decision` after verified task completion.
- `spec_manifest`: deterministic markdown section manifest and task-to-section
  mapping used for spec slicing.
- `cost_ledger`: provider dispatch, token usage, and USD ledger. Unknown usage
  still records dispatch count and does not infer authoritative spend from
  prompt length.
- `budget_cap_usd` and `budget_action`: safe-boundary budget policy.
- `method_evidence_required`: opt-in apply method-evidence gate.
- `hook_config`: runtime hook mode (`off`, `builtin`, or a configured path).
- `intake_recovery`: records strict parser/preflight shape failures, automatic
  repair actions, normalized plan artifact refs, recovery report refs, and
  whether execution may start without user input.

Provider attempts may include `requested_model`, `actual_model`, `usage`, and
`usage_source`. Missing provider usage is represented as `usage: null` with
`usage_source: "unknown"`.

## Related Tests

Inspect `tests/fixtures/contracts/valid-run-state-v2.json` for the fixture
shape. Runtime behavior is covered by `packages/orchestrator/tests/runStateV2.test.ts`,
`packages/orchestrator/tests/orchestratorRunV2.test.ts`,
`packages/orchestrator/tests/applyEngine.test.ts`, and
`packages/lens-projectors/tests/apply.test.ts`.
