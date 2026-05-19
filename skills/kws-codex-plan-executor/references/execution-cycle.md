# Execution Cycle

1. Parse the plan with `scripts/parse_plan.py`.
2. Classify dirty files as related or unrelated before editing.
3. Create `run_id=<plan-slug>-<YYYYMMDD-HHMMSS>`. If the path already exists,
   append a short random suffix.
4. Create a dedicated non-conflicting git worktree under
   `~/.codex/worktrees/<run_id>` after checking `git worktree list --porcelain`
   and existing branches. If a branch name already exists, append the run_id.
5. Do not implement from `main`. Do not implement from the caller's original
   checkout.
6. Create `~/.codex/orchestrator/<run_id>/` for `state.json`, `context.json`,
   `hooks/`, `learning_events/`, raw command evidence, and headless artifacts.
7. Build `context.json` before edits and store `context_snapshot_path` plus
   `context_basis_hash` in state.
8. For each task, state the `TASK EXECUTION CONTRACT`, record `unit_manifest`,
   invoke `using-superpowers`, invoke `test-driven-development` for code
   changes, capture RED evidence, implement, capture GREEN evidence, then run
   the post-diff policy check.
9. Dispatch subagents by default when work can be split safely. Give each
   worker a disjoint write scope and review results before marking the task
   complete. Skip subagents only when `subagents=off`.
10. Maintain `context_health` at every semantic boundary.
11. Before `lifecycle_outcome=finished`, run `scripts/reconcile_state.py` and
    `scripts/validate_state.py`.

AgentLens replay and learning events are best-effort. A failure to emit those
events cannot block implementation.
