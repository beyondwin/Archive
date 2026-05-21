# Waygent Recovery

## First Step

Start with evidence, not a guess:

```bash
waygent inspect --run <run_id> --json
waygent explain --last
```

Use the reported blocker, artifact refs, checkpoint state, and recovery policy
before retrying providers, regenerating checkpoints, resuming, or applying.

## Failure Classes

| Failure | Operator action |
| --- | --- |
| `dirty_source_checkout` | Clean or commit the source checkout before resume or apply. |
| `dependency_missing` | Repair the verification environment and rerun verification. |
| `environment_blocker` | Inspect setup evidence before retrying. |
| `verification_failed` | Fix the task worktree or route to human decision. |
| `artifact_missing` | Inspect checkpoint artifacts before regeneration. |
| `state_drift` | Reconcile drift before apply. |
| duplicate run id | Choose a new run id or resume the existing run. |

## Recovery Actions

Use `waygent resume --last` only when the selected run is unambiguous and the
recovery policy allows the next action. Provider crashes, malformed output, and
timeouts can be retried or routed to another provider only when prior evidence
is preserved. Missing or corrupted checkpoint artifacts require inspection
before regeneration.

Dirty source checkouts block apply. Verification failures require fixing the
task worktree or escalating to a human decision before runtime state can become
ready.

## Stop Conditions

Stop when the run id is ambiguous, source checkout state is dirty for apply,
checkpoint artifacts are missing, state drift is unresolved, or verification
evidence does not match the requested change. Do not invent patches from chat or
bypass `waygent.run_state.v2`.
