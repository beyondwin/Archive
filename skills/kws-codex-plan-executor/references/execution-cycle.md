# Execution Cycle

Use this for `mode=interactive`.

## Phase 0: Preflight

- Read repo-local instructions.
- Verify plan/spec/docs paths.
- Check git status and branch.
- Parse the plan with `scripts/parse_plan.py`.
- Classify dirty files as `related` or `unrelated` against declared task files.
  Stop before editing related dirty files; preserve unrelated dirty files.
- Create a dedicated non-conflicting `codex/...` git worktree for every new
  execution run before any task contract or edits. Do not implement from `main`
  or the caller's original checkout.
  - Inspect `git worktree list --porcelain` and local branches before choosing
    a branch/path.
  - Start from a `codex/<plan-or-task-slug>` branch name. If the branch name
    already exists or a worktree path is already claimed, append the run_id or a
    unique pre-run suffix; once run_id is known, record the final branch and
    worktree in state.
  - Resume may select the worktree recorded in the explicit state path/run id,
    but only if it is still present and matches the stored branch. Otherwise
    stop with a blocker instead of falling back to the original checkout.
- Initialize a learning run inside the selected worktree with
  `scripts/append_learning_event.py init-run` and keep its `run_id` for all
  state, headless artifacts, and learning events.
- Initialize `.codex-orchestrator/runs/<run_id>/state.json` and keep
  `.codex-orchestrator/state.json` as a latest-state compatibility copy or
  pointer.
- Build `.codex-orchestrator/runs/<run_id>/context.json` with
  `scripts/build_context_snapshot.py` after `run_id` initialization and before
  task contracts. Store `context_snapshot_path` and `context_basis_hash` in
  `.codex-orchestrator/runs/<run_id>/state.json`.
- Initialize `context_health` in state after the context snapshot is created.
  It must include `status`, `last_checked_at`, `context_snapshot_present`,
  `context_basis_hash_recorded`, `active_task_contract_present`, `next_action`,
  `open_questions`, `known_assumptions`, and `handoff_ready`.
- For `blocker` outcomes such as unreadable plans, ambiguous resume state,
  related dirty task files, unusable execution worktree, or unclear mid/high-risk
  acceptance criteria, write a redacted learning event using
  `references/learning-log.md` and `scripts/append_learning_event.py append`
  when a run_id exists.
- Assign task risk:
  - `low`: one isolated file or module.
  - `mid`: multiple files, shared config, repeated edits to the same file, or
    unclear verification.
  - `high`: cross-area API/schema/auth/persistence/breaking change.

## Phase 1: Task Loop

For each task:

1. Confirm a 5-line `TASK EXECUTION CONTRACT`:
   - `scope`
   - `files_to_inspect`
   - `allowed_edits`
   - `forbidden_edits`
   - `acceptance_command_or_honest_substitute`
   Record the same contract under the task entry in
   `.codex-orchestrator/runs/<run_id>/state.json`.
2. Re-check task skills before edits. Invoke `using-superpowers` as the
   per-task skill gate. For feature, bugfix, refactor, behavior change, or
   executable-code edits, invoke `test-driven-development` before writing
   implementation code. This applies to interactive and headless execution and
   is not a headless-only rule. Record RED evidence (command/eval plus expected
   failure) in state/checkpoint before implementing, then record GREEN evidence
   after the fix. Docs-only/config-only/generated-only tasks may record TDD as
   not applicable with the reason.
3. Implement locally unless subagents are explicitly allowed.
4. Review spec compliance and code quality on `gpt-5.5 high`.
5. Run risk-scaled verification.
   For `risk=high`, maintain a compact high-risk verification matrix. Include
   each relevant scenario with `status=passed|failed|blocked|not-applicable`,
   the command or manual check, and the evidence path or excerpt:
   - malformed or unexpected input
   - stale state or resume path
   - dirty worktree preservation
   - hung or long-running command behavior
   - misleading success output or skipped tests
   - cancellation/interruption recovery when the task changes workflow state
   Do not run irrelevant scenarios just to fill the table. Mark them
   `not-applicable` with one concrete reason.
6. Record raw output paths for failures.
7. Update state and checkpoint.
   Task completion must set the task `status` to `completed`, `blocked`, or
   `error`; do not leave a finished task as `in_progress` with only
   `completed_at` populated.
8. Refresh `context_health` at the same semantic boundary. Use `green` when
   another agent can resume from state and artifacts, `yellow` when assumptions
   or open questions remain but execution can continue, and `red` when safe
   continuation requires a blocker, user decision, or handoff.

Use `spawn_agent` only when the user explicitly asked for subagents, delegation,
parallel work, or passed `subagents=on`. Otherwise execute locally.

## Review And Retry

- Give each review or verification issue a stable key:
  `ISSUE_KEY=<file>:<line-or-symbol>:<category>`.
- If the same key appears again, mark it as
  `[RECURRING - previous fix did not address this]`.
- Record a `verification_failure` event after raw output is preserved.
- Record a `recurring_issue` event when the same `ISSUE_KEY` appears again.
- Record a `user_correction` event when user feedback changes scope, allowed
  files, or assumptions.
- Record a `successful_workaround` event when a root-cause-based recovery
  exposes a reusable executor improvement.
- Do not repeat the same root-cause fix more than 3 times.
- Preserve raw output for failures under `.codex-orchestrator/runs/<run_id>/raw/`
  when the output is long.

## Phase 2: Finish

- Run final verification.
- Check documentation impact.
- Refresh `context_health` before final state validation. Finished runs must be
  `handoff_ready=true` and not `red`; blocked or failed runs must leave a
  concrete `next_action` and any `open_questions` needed for handoff.
- Write `completion_audit` before claiming completion. It must include
  `passed=true`, non-empty `prompt_to_artifact_checklist`, and non-empty
  `verification_evidence` when `lifecycle_outcome=finished`.
- Set terminal `lifecycle_outcome` to `finished`, `blocked`, or `failed`.
  Non-success outcomes must include a concrete `handoff_reason`.
- Validate state file.
- Record `completion_learning` only when final completion reveals an actionable
  improvement for this executor. Do not log routine successful completions.
- Close the learning run with `scripts/append_learning_event.py close-run` using
  `success`, `blocked`, or `error` for whole-run outcome. Learning-log failure
  must not block the user's implementation result.
- Summarize changed files, verification, branch/worktree, session-owned
  resources, `lifecycle_outcome`, evidence, artifacts/state, `handoff_reason`
  when not finished, and residual risk.

Do not claim completion without fresh verification evidence.
