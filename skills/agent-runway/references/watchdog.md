Source-of-truth: the design document wins when this reference and code disagree.

# Watchdog and Resume Reconciliation

Resume starts by producing a reconciliation plan. `resume --dry-run --json`
returns that plan without writes. Non-dry-run resume applies the plan
idempotently. Watchdog classification still maps process stall, timeout, and
missing result evidence into bounded recovery decisions.

Each worker records `started_at` before adapter execution and terminal
`ended_at` when result collection finishes or the adapter crashes. Later state
transitions such as `merged` or `not_selected` do not overwrite terminal timing.
`agentrunway summarize` reports worker durations so slow, stalled, or orphaned
leases can be identified without loading raw logs.

Stale lease signals:

- `started_at` exists and `ended_at` is empty after the process deadline;
- process liveness is missing for a running worker;
- stdout/stderr exist but no result artifact was written;
- a terminal process snapshot reports timeout, missing, or non-zero exit.

Evidence sources:

- SQLite run, worker, task, merge, artifact, event, applied commit, and worker timing rows
- `run.json`, `contract.json`, `artifact_graph.json`, `coverage.json`, `events.jsonl`
- worker result artifacts and stdout/stderr logs
- process liveness when a PID exists
- git branch heads, worktree paths, and cherry-pick state

Supported actions in this slice:

- `reconcile_forward`: valid artifact exists but DB state is behind
- `retry`: worker is dead and no valid result artifact is present

Reserved (not yet emitted by the planner; see design S10 implementation-scope note):

- `abort_cherry_pick`: run main has an interrupted cherry-pick
- `retain_orphan`: unmatched worktree is kept for diagnostics
- `block`: budget is exhausted or operator action is required

Resume must not duplicate terminal tasks, merge candidates, worker attempts, or
applied commits.
