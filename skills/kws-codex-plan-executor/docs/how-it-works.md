# How It Works

The executor parses a plan, creates an isolated git worktree under
`~/.codex/worktrees/<run_id>`, and writes orchestration state under
`~/.codex/orchestrator/<run_id>`.

Implementation follows a task contract, RED/GREEN verification, drift
reconciliation, and final state validation. Prompt and handoff modes only export
text.

For v2.20+ runs, the executor also builds spec manifests and task packets so
the active task sees only the plan slice, spec slice, decisions, and write scope
it needs. Compaction points write durable state anchors and make prior raw task
context disposable.

Task packets describe why context was included. `context_components` records
task body, spec slice or full fallback, write policy, and acceptance contract
hashes. `context_budget` records the largest component and component totals so
large packets can be reduced deliberately.

With the default `subagents=on`, CPE uses adaptive dispatch. Eligible
write-capable tasks first pass safety checks, then a value check decides whether
to delegate or run local fast path. Local fast path skips only the subagent
spawn/review loop; it keeps task contracts, RED/GREEN evidence when applicable,
diff policy checks, acceptance commands, reconciliation, and state validation.

Command observations feed a bounded recovery policy. The policy can retry flaky
or timeout roots, allow one dependency bootstrap, continue source-failure
implementation loops, block permission or diff-scope gaps, or fail after retry
budget exhaustion. Trajectory and progress ledger records make those choices
auditable without full transcript replay.
