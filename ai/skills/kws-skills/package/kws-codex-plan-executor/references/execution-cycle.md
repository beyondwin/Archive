# Execution Cycle

Use this for `mode=interactive`.

## Phase 0: Preflight

- Read repo-local instructions.
- Verify plan/spec/docs paths.
- Check git status and branch.
- Parse the plan with `scripts/parse_plan.py`.
- Classify dirty files as `related` or `unrelated` against declared task files.
  Stop before editing related dirty files; preserve unrelated dirty files.
- Initialize a learning run with `scripts/append_learning_event.py init-run` and
  keep its `run_id` for all state, headless artifacts, and learning events.
- For `blocker` outcomes such as unreadable plans, ambiguous resume state,
  related dirty task files, or unclear mid/high-risk acceptance criteria, write
  a redacted learning event using `references/learning-log.md` and
  `scripts/append_learning_event.py append`.
- Create or select `codex/...` worktree when appropriate.
- Assign task risk:
  - `low`: one isolated file or module.
  - `mid`: multiple files, shared config, repeated edits to the same file, or
    unclear verification.
  - `high`: cross-area API/schema/auth/persistence/breaking change.
- Initialize `.codex-orchestrator/runs/<run_id>/state.json` and keep
  `.codex-orchestrator/state.json` as a latest-state compatibility copy or
  pointer.

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
2. Implement locally unless subagents are explicitly allowed.
3. Review spec compliance and code quality on `gpt-5.5 high`.
4. Run risk-scaled verification.
5. Record raw output paths for failures.
6. Update state and checkpoint.
   Task completion must set the task `status` to `completed`, `blocked`, or
   `error`; do not leave a finished task as `in_progress` with only
   `completed_at` populated.

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
- Validate state file.
- Record `completion_learning` only when final completion reveals an actionable
  improvement for this executor. Do not log routine successful completions.
- Close the learning run with `scripts/append_learning_event.py close-run` using
  `success`, `blocked`, or `error` for whole-run outcome. Learning-log failure
  must not block the user's implementation result.
- Summarize changed files, verification, branch/worktree, session-owned
  resources, and residual risk.

Do not claim completion without fresh verification evidence.
