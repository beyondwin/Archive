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
