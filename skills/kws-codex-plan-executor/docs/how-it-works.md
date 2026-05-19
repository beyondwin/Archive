# How It Works

The executor parses a plan, creates an isolated git worktree under
`~/.codex/worktrees/<run_id>`, and writes orchestration state under
`~/.codex/orchestrator/<run_id>`.

Implementation follows a task contract, RED/GREEN verification, drift
reconciliation, and final state validation. Prompt and handoff modes only export
text.
