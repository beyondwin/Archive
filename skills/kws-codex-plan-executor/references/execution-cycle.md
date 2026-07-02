# Execution Cycle

1. Parse the plan with `scripts/parse_plan.py`.
2. Run `scripts/inspect_runs.py` for the target plan. If one unambiguous active
   run exists and the invocation did not request resume, stop and ask whether to
   resume or start a new run. If multiple active runs exist, stop with the
   stale-run report. Do not mutate stale runs automatically.
3. When current Superpowers skills are available for an approved interactive
   implementation plan, run
   `scripts/audit_superpowers_compatibility.py`. If it recommends
   `thin_stateful_bridge`, route implementation through the current
   Superpowers-native loop while preserving the remaining CPE state and audit
   steps below. If it fails, continue only with an explicit CPE-owned fallback
   or stop when compatibility is required.
4. Classify dirty files as related or unrelated before editing.
5. Create `run_id=<plan-slug>-<YYYYMMDD-HHMMSS>`. If the path already exists,
   append a short random suffix.
6. Create a dedicated non-conflicting git worktree under
   `~/.codex/worktrees/<run_id>` after checking `git worktree list --porcelain`
   and existing branches. If a branch name already exists, append the run_id.
7. Do not implement from `main`. Do not implement from the caller's original
   checkout.
8. Create `~/.codex/orchestrator/<run_id>/` for `state.json`, `context.json`,
   `hooks/`, `learning_events/`, raw command evidence, and headless artifacts.
9. Build `context.json` before edits and store `context_snapshot_path` plus
   `context_basis_hash` in state. When `spec_manifest.json` or task packets are
   present, pass `--spec-manifest` and `--task-packet-dir` so the snapshot
   records summaries and packet indexes instead of raw packet text.
   When task packets are present, generate task packet human views under
   `$RUN_DIR/task_packets/*.md` before prompt, handoff, or subagent context uses
   them. Treat these views as derived readability artifacts only.
10. Before task execution, run `scripts/audit_run_readiness.py` against
   `$RUN_DIR/task_packets`. Save the JSON as `$RUN_DIR/run_readiness.json` and
   copy its summary into `run_quality.readiness` when finalizing. If it reports
   blocking issues, stop before edits; if it reports fixable issues, record the
   operator decision before continuing. For comma-joined write scopes, use the
   reported `suggested_write_scopes`/`normalized_write_globs` values when
   re-running dispatch instead of guessing from the raw string.
11. Run `scripts/audit_plan_executability.py` against the parsed plan JSON and
    `$RUN_DIR/task_packets` when packets exist. Save the JSON as
    `$RUN_DIR/plan_executability_audit.json`, print the short readiness summary,
    and copy `grade`, `blocking_issue_count`, `fixable_issue_count`, and raw
    count fields when operator review changes effective counts into state as
    `plan_executability_audit`. Blocking audit issues stop execution before
    task contracts or edits unless an explicit operator review records
    `operator_reviewed_blocking_issues` and `operator_decision`.
12. Resolve skill paths from the active skill registry/root mapping before
   reading local skill files. Do not hard-code `.system` or any other root. If a
   read fails, re-check the registry entry and root table first; classify it as
   an operator path-resolution error unless the registry itself is proven stale.
13. If repo instructions mention graphify, run:
    `python3 scripts/check_graphify_freshness.py --repo-root "$WORKTREE_ABS" --output "$RUN_DIR/graphify_audit.json"`.
    After code changes or meaningful documentation-structure changes, run
    `graphify update .`, then
    `python3 scripts/check_graphify_freshness.py --repo-root "$WORKTREE_ABS" --update-ran --output "$RUN_DIR/graphify_audit.json"`.
    Copy or reference the JSON result in state as `graphify_audit` and in
    `completion_audit.verification_evidence`; finished state validation rejects
    Graphify audit evidence that is not connected to completion evidence.
14. For each task, state the `TASK EXECUTION CONTRACT`, record `unit_manifest`,
   invoke `using-superpowers`, invoke `test-driven-development` for code
   changes, capture RED evidence, implement, capture GREEN evidence, then run
   the post-diff policy check.
15. Run `scripts/preflight_dispatch.py` before each eligible write-capable task.
    Dispatch only when the decision is `delegate`. When the decision is
    `local_fallback` with an adaptive local fast path reason, run the task
    locally but keep the same quality gates: task contract, unit manifest,
    RED/GREEN when applicable, post-diff review, acceptance command,
    reconciliation, and state validation. When the decision is `block`, stop
    before editing and record the blocker.
16. Maintain `context_health` at every semantic boundary.
17. Before `lifecycle_outcome=finished`, run `scripts/reconcile_state.py` and
    `scripts/validate_state.py`.
    When using project-level verification bundles, record them as structured
    `completion_audit.verification_evidence` objects with
    `class=verification_bundle`; keep acceptance command evidence separate.
18. When replay behavior, residual risk, run-quality debt, or audit parity
    changes, run `scripts/normalize_cpe_run.py` through
    `evals/check_cpe_replay.py` and reference that deterministic evidence.

When finalizing `run_quality`, include state-intrinsic operational debt
follow-ups before running `validate_state.py`. Read-only inspection may add
current observations such as `missing_execution_worktree` after completion
without mutating state; those observations use `observed_after_completion=true`.

AgentLens replay and learning events are best-effort. A failure to emit those
events cannot block implementation.
