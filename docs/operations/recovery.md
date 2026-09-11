# Recovery

Start with the records:

```bash
waygent inspect --run <run_id> --json
waygent explain --last
```

Read the blocker, file refs, checkpoint state, and recovery policy before
you retry, regenerate, resume, or apply.

| Failure | What to do |
| --- | --- |
| `dirty_source_checkout` | Clean or commit before resume/apply |
| `dependency_missing` | Fix the check env, rerun the check |
| `environment_blocker` | Inspect setup records |
| `verification_failed` | Fix the task copy or escalate |
| `artifact_missing` | Inspect checkpoints before regenerating |
| `state_drift` | Match-check before apply |
| duplicate run id | New id, or resume the existing run |
| `needs_rebase` | Regenerate/rebase the checkpoint; do not apply the stale patch |
| budget paused | `waygent cost --last`, then raise or disable the cap |
| `review_evidence_missing` | `waygent review --run <id>` |
| `lens.evidence_apply_blocked` | Extra proof, or an allowlisted waiver |

`waygent resume --last` only when the run pick is clear and policy
allows the next action. Provider crashes, bad output, and timeouts can retry
or switch provider if prior records are kept.

## Scope failures

None of these create a checkpoint or release dependents:

- `generated_artifact_unclaimed` — generated files outside `allowed_write_globs`
- `forbidden_write` — `.git/**`, `node_modules/**`, and similar. No retry.
- `provider_claim_gap` — changed files the provider did not report
- `provider_overreach` — unrelated files. One retry with records, then a
  decision.

Patch-bearing `verification_failed` goes to focused repair first.
`malformed_result`, `adapter_crashed`, and `timeout` with a bounded captured
diff record `waygent.salvage_result.v1` and stay review-required. Salvage is
not success.

## Stop

Stop when the run id is unclear, apply would hit a dirty checkout,
checkpoints are missing, unexpected changes are unresolved, or the check does
not match the change. Do not invent patches from chat.
