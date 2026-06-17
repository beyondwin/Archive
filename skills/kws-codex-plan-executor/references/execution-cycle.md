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
   `context_basis_hash` in state. When `spec_manifest.json` or task packets are
   present, pass `--spec-manifest` and `--task-packet-dir` so the snapshot
   records summaries and packet indexes instead of raw packet text.
9. Resolve skill paths from the active skill registry/root mapping before
   reading local skill files. Do not hard-code `.system` or any other root. If a
   read fails, re-check the registry entry and root table first; classify it as
   an operator path-resolution error unless the registry itself is proven stale.
10. If repo instructions mention graphify, run:
    `python3 scripts/check_graphify_freshness.py --repo-root "$WORKTREE_ABS" --output "$RUN_DIR/graphify_audit.json"`.
    After code changes or meaningful documentation-structure changes, run
    `graphify update .`, then
    `python3 scripts/check_graphify_freshness.py --repo-root "$WORKTREE_ABS" --update-ran --output "$RUN_DIR/graphify_audit.json"`.
    Copy or reference the JSON result in state as `graphify_audit` and in
    `completion_audit.verification_evidence`.
11. For each task, state the `TASK EXECUTION CONTRACT`, record `unit_manifest`,
   invoke `using-superpowers`, invoke `test-driven-development` for code
   changes, capture RED evidence, implement, capture GREEN evidence, then run
   the post-diff policy check.
12. Run `scripts/preflight_dispatch.py` before each eligible write-capable task.
    Dispatch only when the decision is `delegate`. When the decision is
    `local_fallback` with an adaptive local fast path reason, run the task
    locally but keep the same quality gates: task contract, unit manifest,
    RED/GREEN when applicable, post-diff review, acceptance command,
    reconciliation, and state validation. When the decision is `block`, stop
    before editing and record the blocker.
13. Maintain `context_health` at every semantic boundary.
14. Before `lifecycle_outcome=finished`, run `scripts/reconcile_state.py` and
    `scripts/validate_state.py`.

AgentLens replay and learning events are best-effort. A failure to emit those
events cannot block implementation.
