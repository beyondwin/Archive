# Execution Cycle

Use this for `mode=interactive`.

## Phase 0: Preflight

- Read repo-local instructions.
- Verify plan/spec/docs paths.
- Check git status and branch.
- Classify dirty files as `related` or `unrelated` against declared task files.
  Stop before editing related dirty files; preserve unrelated dirty files.
- Create or select `codex/...` worktree when appropriate.
- Parse the plan with `scripts/parse_plan.py`.
- Assign task risk:
  - `low`: one isolated file or module.
  - `mid`: multiple files, shared config, repeated edits to the same file, or
    unclear verification.
  - `high`: cross-area API/schema/auth/persistence/breaking change.
- Initialize `.codex-orchestrator/state.json`.

## Phase 1: Task Loop

For each task:

1. Confirm a 5-line `TASK EXECUTION CONTRACT`:
   - `scope`
   - `files_to_inspect`
   - `allowed_edits`
   - `forbidden_edits`
   - `acceptance_command_or_honest_substitute`
   Record the same contract under the task entry in
   `.codex-orchestrator/state.json`.
2. Implement locally unless subagents are explicitly allowed.
3. Review spec compliance and code quality on `gpt-5.5 high`.
4. Run risk-scaled verification.
5. Record raw output paths for failures.
6. Update state and checkpoint.

Use `spawn_agent` only when the user explicitly asked for subagents, delegation,
parallel work, or passed `subagents=on`. Otherwise execute locally.

## Review And Retry

- Give each review or verification issue a stable key:
  `ISSUE_KEY=<file>:<line-or-symbol>:<category>`.
- If the same key appears again, mark it as
  `[RECURRING - previous fix did not address this]`.
- Do not repeat the same root-cause fix more than 3 times.
- Preserve raw output for failures under `.codex-orchestrator/raw/` when the
  output is long.

## Phase 2: Finish

- Run final verification.
- Check documentation impact.
- Validate state file.
- Summarize changed files, verification, branch/worktree, session-owned
  resources, and residual risk.

Do not claim completion without fresh verification evidence.
