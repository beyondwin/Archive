# Run file

`waygent.run_state.v2` is the saved run file: task status, provider
attempts, checks, review, recovery, unexpected file changes, the final check,
and ready-to-apply.

Events, API, and console can replay those records. They do not replace the
run file.

## Tasks

Pending, running, verified, failed, blocked, completed. Each task keeps ids,
file claims, provider attempts, check records, and review records.

Extra fields you may also see:

- `evidence_policy` — optional extra proof of how the work was done
- `hook_retries` — hook denials
- `model_used` — which model ran, when present

## Task packets

- `plan_excerpt` — plan body for this task
- `spec_excerpt` — spec slice, or the full spec if slicing misses
- `allowed_exec_commands` — check commands the sandbox should allow, or
  `null` when the workspace is unknown

## Groups and checkpoints

Groups respect dependencies, file claims, risk, and checkpoints. Checkpoint
refs point at manifests, patch bytes, digest/length, and dry-run results.
Empty patches are valid only as explicit no-op records.

## Final check, match check, apply

The final check confirms outcomes, records, checkpoints, and status agree.
The match check looks for missing files, digest mismatches, and unexpected
source changes.

Apply is `ready`, `not_ready`, `blocked`, or `applied`. `ready` needs verified
checkpoints, combined patch records, a passed dry-run, a clean source repo, no
unfixed unexpected changes, and a passed final check.

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
