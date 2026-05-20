Source-of-truth: the design document wins when this reference and code disagree.

# Watchdog and Resume Reconciliation

Resume starts by producing a reconciliation plan. `resume --dry-run --json`
returns that plan without writes. Non-dry-run resume applies the plan
idempotently. Watchdog classification still maps process stall, timeout, and
missing result evidence into bounded recovery decisions.

Evidence sources:

- SQLite run, worker, task, merge, artifact, event, and applied commit rows
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
