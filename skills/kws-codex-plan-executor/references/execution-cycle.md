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
- Run local environment preflight immediately after worktree creation and
  before baseline verification. Check for ignored machine-local files or state
  that git will not copy into a new worktree:
  - Android/Gradle: `local.properties` with `sdk.dir`; compare against the
    original checkout discovered from `git worktree list --porcelain` when
    available.
  - Node/frontend: dependency install state for the selected package manager
    before build or test commands.
  - Docker build tasks: Docker daemon reachability and available memory when
    the plan includes containerized builds.
  - Local env templates: `.env.example` exists while `.env` is intentionally
    absent.
  Do not silently copy ignored files. If a missing local file blocks baseline
  verification, ask the user, copy only after explicit approval, or record an
  honest substitute explaining the environment blocker.
- Generate the run id and create the project-local run dir before any edits.
  The run id encodes UTC time, repo slug, branch slug, head hash, and a random
  suffix (e.g. `20260519T085338Z-archive-codex-events-abcdef0-a1b2c3`). Keep
  the same `run_id` across project-local state, headless artifacts, and every
  AgentLens emit for this run.
- Open an AgentLens orchestration run alongside the learning run init, capturing
  the id for the lifetime of this execution:

  ```bash
  ORCH_RUN_ID=$(agentlens run-open \
    --agent kws-cpe-orchestrator \
    --workspace "$WORKTREE_ABS" \
    --meta plan="$PLAN_REL" \
    --meta spec="${SPEC_REL:-}" \
    2>/dev/null || echo "")
  ```

  If `ORCH_RUN_ID` is empty (CLI absent, registry error), all later AgentLens
  emit sites no-op silently. AgentLens failure is never a blocker.
- Initialize `.codex-orchestrator/runs/<run_id>/state.json` and keep
  `.codex-orchestrator/state.json` as a latest-state compatibility copy or
  pointer. Persist `agentlens_orchestration_run` at the top of the per-run
  state.json (string id or `null`); this field is run-level and must be
  preserved across resume/handoff.
- Initialize replay evidence by emitting `kws-cpe.run_started` to AgentLens.
  This is now the canonical event sink — the legacy
  `scripts/append_run_event.py` helper was removed at the v2.18 cutover.

  ```bash
  if [ -n "${ORCH_RUN_ID:-}" ]; then
    agentlens event append --run "$ORCH_RUN_ID" \
      --type kws-cpe.run_started \
      --payload-json '{"mode":"interactive","run_id":"<run_id>"}' \
      2>/dev/null || true
  fi
  ```

  `state.json` remains the authoritative resumable record; the AgentLens stream
  is replay evidence and does not replace it.
- Build `.codex-orchestrator/runs/<run_id>/context.json` with
  `scripts/build_context_snapshot.py` after `run_id` initialization and before
  task contracts. Store `context_snapshot_path` and `context_basis_hash` in
  `.codex-orchestrator/runs/<run_id>/state.json`.
  Pass `--max-chars` when a run needs an explicit context budget; the snapshot
  records `context_budget.status`, `estimated_chars`, `included_sections`, and
  `omitted_sections` without changing the source-list `basis_hash`.
- Initialize `context_health` in state after the context snapshot is created.
  It must include `status`, `last_checked_at`, `context_snapshot_present`,
  `context_basis_hash_recorded`, `active_task_contract_present`, `next_action`,
  `open_questions`, `known_assumptions`, and `handoff_ready`.
- For `blocker` outcomes such as unreadable plans, ambiguous resume state,
  related dirty task files, unusable execution worktree, or unclear mid/high-risk
  acceptance criteria, write a redacted learning event directly to AgentLens
  per `references/learning-log.md`. Emit `kws-cpe.learning.blocker` when
  `ORCH_RUN_ID` is non-empty:

  ```bash
  if [ -n "${ORCH_RUN_ID:-}" ]; then
    agentlens event append --run "$ORCH_RUN_ID" \
      --type kws-cpe.learning.blocker \
      --payload-json '<redacted-event-json>' \
      2>/dev/null || true
  fi
  ```
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
   Executable tasks may also record `unit_manifest` with `unit_type`,
   `context_mode`, `required_skills`, `tool_policy`, `allowed_write_globs`,
   `forbidden_write_globs`, `artifact_policy`, and `max_context_chars`.
   Finished runs require every completed task to have a valid manifest.
   Append `task_contract_recorded` after the contract is saved when the event
   journal is active. Dual-write the mirror to AgentLens as
   `kws-cpe.task_started` when `ORCH_RUN_ID` is non-empty:

   ```bash
   if [ -n "${ORCH_RUN_ID:-}" ]; then
     agentlens event append --run "$ORCH_RUN_ID" \
       --type kws-cpe.task_started \
       --payload-json '{"task_id":"<task_id>"}' \
       2>/dev/null || true
   fi
   ```
2. Re-check task skills before edits. Invoke `using-superpowers` as the
   per-task skill gate. For feature, bugfix, refactor, behavior change, or
   executable-code edits, invoke `test-driven-development` before writing
   implementation code. This applies to interactive and headless execution and
   is not a headless-only rule. Record RED evidence (command/eval plus expected
   failure) in state/checkpoint before implementing, then record GREEN evidence
   after the fix. Docs-only/config-only/generated-only tasks may record TDD as
   not applicable with the reason.
   Record required phase methods in `method_audit` by evidence, not by intent.
   TDD requires RED and GREEN evidence, review requires findings or an explicit
   no-findings residual-risk statement, and completion verification requires
   command evidence. Do not record routine helper skills; record required
   methods and explicit waivers only.
3. Implement locally unless subagents are explicitly allowed. If subagents are
   explicitly allowed, set `subagents_requested=true` in state and record each
   delegated run under `subagent_runs` with owner task, write scope, status,
   result summary, changed files, review status, and any overlap rationale.
   Finished runs cannot contain running or unreviewed subagent records.
4. Review spec compliance and code quality on `gpt-5.5 high`.
5. Run risk-scaled verification.
   When a command result needs triage before root cause is assigned, record a
   compact `command_observations[]` entry in state with command, status,
   taxonomy category, bounded evidence, and next action. Use
   `category=unknown` only with bounded evidence; terminal finished runs must
   also mention that command in `completion_audit.residual_risk`.
   Parallel verification is allowed only when commands do not share mutable
   output resources. Assign a `verification_resource_key` before parallelizing
   commands that can write shared artifacts:
   - Gradle Test task:
     `gradle-test:<project-path>:<task-name>:<test-results-dir>`
   - Gradle build task: `gradle-build:<project-path>`
   - Node package command: `node:<package-dir>:<command-name>`
   - Docker build: `docker-build:<dockerfile-path>:<context-path>:<tag>`
   - Browser/E2E command: `browser:<app-url-or-project>:<suite>`
   Commands with the same resource key run serially in one worktree. Record the
   serialization reason in state when this changes the verification plan.
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
   Before closing a task that records `unit_manifest`, run or honestly
   substitute `scripts/check_run_diffs.py --repo-root <worktree> --state
   .codex-orchestrator/runs/<run_id>/state.json --task <task_id>` so changed
   files are checked against `contract.allowed_edits`,
   `unit_manifest.allowed_write_globs`, `contract.forbidden_edits`, and
   `unit_manifest.forbidden_write_globs`.
   Append `verification_passed` or `verification_failed` for task-level
   verification boundaries when the event journal is active. Dual-write to
   AgentLens as `kws-cpe.verification_failed` (the failure case is the spec'd
   primary event; emit `kws-cpe.verification_passed` for symmetry on success)
   when `ORCH_RUN_ID` is non-empty:

   ```bash
   if [ -n "${ORCH_RUN_ID:-}" ]; then
     agentlens event append --run "$ORCH_RUN_ID" \
       --type "kws-cpe.verification_${RESULT}" \
       --payload-json '{"task_id":"<task_id>","command":"<cmd>"}' \
       2>/dev/null || true
   fi
   ```
6. Record raw output paths for failures.
7. Update state and checkpoint.
   Task completion must set the task `status` to `completed`, `blocked`, or
   `error`; do not leave a finished task as `in_progress` with only
   `completed_at` populated.
   When `task_completed` is appended to the project-local event journal,
   dual-write the mirror to AgentLens as `kws-cpe.task_completed` when
   `ORCH_RUN_ID` is non-empty:

   ```bash
   if [ -n "${ORCH_RUN_ID:-}" ]; then
     agentlens event append --run "$ORCH_RUN_ID" \
       --type kws-cpe.task_completed \
       --payload-json '{"task_id":"<task_id>","status":"completed"}' \
       2>/dev/null || true
   fi
   ```
8. Refresh `context_health` at the same semantic boundary. Use `green` when
   another agent can resume from state and artifacts, `yellow` when assumptions
   or open questions remain but execution can continue, and `red` when safe
   continuation requires a blocker, user decision, or handoff. Whenever any
   `context_health` field changes, update `context_health.last_checked_at` in
   the same state write. A stale timestamp is misleading during resume because
   `next_action` can look fresh while the health check date still points at an
   earlier task.

When sequential tasks share one acceptance metric, record task-level
`carried_acceptance` instead of marking the metric silently green. Use
`status=open` while a later task is expected to resolve it. Before
`lifecycle_outcome=finished`, every carried acceptance entry must be `resolved`
or `accepted_with_rationale`, and final metric evidence must be present in the
completion audit.

For React Router work that converts static route objects to lazy route objects,
include route tests and test harness helpers in `allowed_edits` unless the plan
explicitly forbids test changes. Expected verification risks are asynchronous
lazy route rendering, missing `hydrateFallbackElement`, request construction
through existing test shims, and public navigation/auth tests that need async
assertions even when product behavior is unchanged. Keep this guidance scoped to
React Router lazy-route tasks.

Use `spawn_agent` only when the user explicitly asked for subagents, delegation,
parallel work, or passed `subagents=on`. Otherwise execute locally.

## Resource Failure Triage

When Docker, Gradle, or Kotlin build failures could be environmental, gather
resource evidence before changing project source.

Docker build triage:

1. Identify the failed builder container when available.
2. Check OOM state with redaction-safe evidence:

   ```bash
   docker inspect <container-id> --format '{{.State.OOMKilled}}'
   ```

3. If OOM is true, treat it as environment/resource evidence before changing
   source code.

Gradle daemon disappearance triage should distinguish:

- container OOM
- JVM metaspace or heap limit
- Kotlin daemon memory pressure
- daemon crash unrelated to source
- real compile or test failure

If a bounded retry succeeds after resource adjustment, record a
`successful_workaround` event with the resource category and bounded command.
When verification still fails, record `verification_failure`; when the same
stable `ISSUE_KEY` repeats, record `recurring_issue`. Learning events should use
shortened container identifiers or redacted summaries, not unrelated process
details.

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
- Run drift reconciliation with `scripts/reconcile_state.py --check` or
  `--repair-safe` before terminal `lifecycle_outcome=finished`. Unrepaired
  blocking drift prevents a finished outcome and requires a concrete
  `handoff_reason` or `context_health.next_action`.
- Check documentation impact.
- Refresh `context_health` before final state validation. Finished runs must be
  `handoff_ready=true`, not `red`, and have `context_health.last_checked_at`
  present and at least as recent as `timestamps.updated_at`; blocked or failed
  runs must leave a concrete `next_action` and any `open_questions` needed for
  handoff.
- Write `completion_audit` before claiming completion. It must include
  `passed=true`, non-empty `prompt_to_artifact_checklist`, and non-empty
  `verification_evidence` when `lifecycle_outcome=finished`.
- Set terminal `lifecycle_outcome` to `finished`, `blocked`, or `failed`.
  Non-success outcomes must include a concrete `handoff_reason`.
- Validate state file.
- Record `completion_learning` only when final completion reveals an actionable
  improvement for this executor. Do not log routine successful completions.
- Close the AgentLens orchestration run with the terminal event and
  `run-close`. Pick the event type by outcome (`finished` →
  `kws-cpe.run_completed`, blocked/failed → emit `kws-cpe.blocker` /
  `kws-cpe.failed` from the relevant taxonomy site) and then close the run.
  AgentLens failure must not block the user's implementation result. Both
  calls are guarded and silent:

  ```bash
  if [ -n "${ORCH_RUN_ID:-}" ]; then
    agentlens event append --run "$ORCH_RUN_ID" \
      --type kws-cpe.run_completed \
      --payload-json '{"outcome":"<finished|blocked|failed>"}' \
      2>/dev/null || true
    agentlens run-close --run "$ORCH_RUN_ID" \
      --outcome "<success|blocked|aborted>" 2>/dev/null || true
  fi
  ```
- Summarize changed files, verification, branch/worktree, session-owned
  resources, `lifecycle_outcome`, evidence, artifacts/state, `handoff_reason`
  when not finished, and residual risk.

Do not claim completion without fresh verification evidence.
