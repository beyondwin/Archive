# Attempt And Subagent Evidence

Every worker attempt belongs to one task and has a unique ID, role, requested
route, actual route attestation, lifecycle result, usage, latency, and evidence
refs. Task packets, not the full plan, define a worker's context and write
scope. `scout`, `implementation`, `task_review`, `verification`, `repair`, and
`final_review` all receive the same manifest-indexed packet path and verified
`packet_sha256`, plus the current `worktree_revision`.

Write-capable attempts are serialized. Read-only scout attempts may be bounded
and concurrent only when their task has no write claim and their output cannot
make implementation, review, verification, or completion decisions.

The controller accepts a write result only after checking worker cwd and git
root, the isolated worktree boundary, the full measured filesystem and Git
delta against the task claim, output schema, and evidence digests. Worker-
reported files are advisory. Accepted implementation or repair writes advance
revision and store immutable patch evidence; review roles are always read-only.
Rejected and superseded attempts remain in event history.

Models return structured results. The transition kernel, not a model or
subagent, appends durable events and rebuilds the state projection.
Typed review verdicts are accepted only when their task, attempt, packet,
`worktree_revision`, and `worktree_patch_sha256` match current projected state.
