# Execution Cycle

1. Parse the plan with `scripts/parse_plan.py`.
2. Run `scripts/inspect_runs.py` for the target plan. If one unambiguous active
   run exists and the invocation did not request resume, stop and ask whether to
   resume or start a new run. If multiple active runs exist, stop with the
   stale-run report. Do not mutate stale runs automatically.
3. Classify dirty files as related or unrelated before editing.
4. Create `run_id=<plan-slug>-<YYYYMMDD-HHMMSS>`. If the path already exists,
   append a short random suffix.
5. Create a dedicated non-conflicting git worktree under
   `~/.codex/worktrees/<run_id>` after checking `git worktree list --porcelain`
   and existing branches. If a branch name already exists, append the run_id.
6. Do not implement from `main`. Do not implement from the caller's original
   checkout.
7. Create `~/.codex/orchestrator/<run_id>/` for `state.json`, `context.json`,
   `hooks/`, `learning_events/`, raw command evidence, and headless artifacts.
8. Build `context.json` before edits and store `context_snapshot_path` plus
   `context_basis_hash` in state.
9. For each task, state the `TASK EXECUTION CONTRACT`, record `unit_manifest`,
   invoke `using-superpowers`, invoke `test-driven-development` for code
   changes, capture RED evidence, implement, capture GREEN evidence, then run
   the post-diff policy check.
10. Dispatch subagents only when the user explicitly requested subagents,
   delegation, or parallel agent work, or passed `subagents=on`. Give each
   worker a disjoint write scope and review results before marking the task
   complete. Keep the run local for `subagents=auto` without an explicit
   request, and always keep it local for `subagents=off`.
11. Maintain `context_health` at every semantic boundary.
12. Before `lifecycle_outcome=finished`, run `scripts/reconcile_state.py` and
    `scripts/validate_state.py`.

AgentLens replay and learning events are best-effort. A failure to emit those
events cannot block implementation.
