# Attempt And Subagent Evidence

Every worker attempt belongs to one task and has a unique ID, kind, requested
route, actual route attestation, lifecycle result, usage, latency, and evidence
refs. Task packets, not the full plan, define a worker's context and write
scope.

Write-capable attempts are serialized. Read-only scout attempts may be bounded
and concurrent only when their task has no write claim and their output cannot
make implementation, review, verification, or completion decisions.

The parent accepts a write result only after checking worker cwd and git root,
the isolated worktree boundary, changed files against the task claim, output
schema, evidence digests, and review status. Rejected and superseded attempts
remain in event history. Only one accepted final attempt may own a given task
write scope.

Models return structured results. The transition kernel, not a model or
subagent, appends durable events and rebuilds the state projection.
