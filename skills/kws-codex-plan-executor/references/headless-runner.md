# Headless Runner

Use this only for `mode=headless`, eval, CI, or explicitly detached execution.

## Skill Bootstrap

Headless starts a fresh `codex exec` process. Do not assume the parent session's
loaded skills carry over. The prompt passed as `$PROMPT` must explicitly tell
the target run to load and follow applicable installed skills, including
`using-superpowers` before any implementation or clarification and
`test-driven-development` before feature, bugfix, refactor, or behavior-change
implementation. This is not a headless-only rule: interactive and headless
execution both require TDD for implementation work. Headless merely needs the
explicit bootstrap because it is a fresh process. The target must record RED
evidence before implementation and GREEN evidence after the fix.

## Caller And Target Boundary

The supervising session launches the command below. The headless target process
that receives `$PROMPT` is already inside `codex exec`; it must execute the task
locally and write the required `.codex-orchestrator/` artifacts. Do not launch
another nested `codex exec` from the target process.

## Mandatory Worktree Gate

Before launching `codex exec`, the supervising session must create a dedicated
non-conflicting `codex/...` git worktree and set `WORKTREE_ABS` to that path.
Do not implement from `main` or from the caller's original checkout.

Use `git worktree list --porcelain` plus local branch checks before selecting
the branch/path. If a branch name already exists or the path is claimed, append
the run_id or a unique pre-run suffix before launch. Resume may use only the
worktree recorded in the explicit state path/run id; if that worktree is absent
or points at another branch, stop with a blocker.

After the worktree exists and before baseline commands, run local environment
preflight. Check for ignored machine-local files or state the project needs but
git did not copy, such as Android `local.properties`, missing Node dependency
installs for the selected package manager, Docker daemon or memory constraints
for container builds, and `.env.example` without a corresponding local `.env`.
Do not silently copy ignored files into the headless worktree. If the missing
file or state blocks baseline verification, the target must ask/report before
copying or record an honest substitute.

## Safe Default Command

```bash
RUN_ID="$(python3 "$SKILL_DIR/scripts/append_learning_event.py" init-run \
  --repo-root "$WORKTREE_ABS" \
  --repo-name "$REPO_NAME" \
  --branch "$BRANCH" \
  --head "$HEAD_SHA" \
  --plan-path "$PLAN_REL" \
  --spec-path "${SPEC_REL:-}" \
  --mode headless)"
RUN_DIR="$WORKTREE_ABS/.codex-orchestrator/runs/$RUN_ID"
mkdir -p "$RUN_DIR/raw"
HEADLESS_SANDBOX="${HEADLESS_SANDBOX:-workspace-write}"
CONTEXT_BASIS_HASH="$(python3 "$SKILL_DIR/scripts/build_context_snapshot.py" \
  --repo-root "$WORKTREE_ABS" \
  --run-id "$RUN_ID" \
  --plan "$PLAN_REL" \
  --spec "${SPEC_REL:-}" \
  --docs "${DOCS_REL:-}" \
  --max-chars "${CONTEXT_MAX_CHARS:-120000}" \
  --output "$RUN_DIR/context.json")"

codex exec \
  --cd "$WORKTREE_ABS" \
  --sandbox "$HEADLESS_SANDBOX" \
  --json \
  --output-last-message "$RUN_DIR/headless-final.md" \
  "$PROMPT" \
  > "$RUN_DIR/headless.jsonl" 2>&1
```

## Schema Output Variant

```bash
RUN_ID="$(python3 "$SKILL_DIR/scripts/append_learning_event.py" init-run \
  --repo-root "$WORKTREE_ABS" \
  --repo-name "$REPO_NAME" \
  --branch "$BRANCH" \
  --head "$HEAD_SHA" \
  --plan-path "$PLAN_REL" \
  --spec-path "${SPEC_REL:-}" \
  --mode headless)"
RUN_DIR="$WORKTREE_ABS/.codex-orchestrator/runs/$RUN_ID"
mkdir -p "$RUN_DIR/raw"
HEADLESS_SANDBOX="${HEADLESS_SANDBOX:-workspace-write}"
CONTEXT_BASIS_HASH="$(python3 "$SKILL_DIR/scripts/build_context_snapshot.py" \
  --repo-root "$WORKTREE_ABS" \
  --run-id "$RUN_ID" \
  --plan "$PLAN_REL" \
  --spec "${SPEC_REL:-}" \
  --docs "${DOCS_REL:-}" \
  --max-chars "${CONTEXT_MAX_CHARS:-120000}" \
  --output "$RUN_DIR/context.json")"

codex exec \
  --cd "$WORKTREE_ABS" \
  --sandbox "$HEADLESS_SANDBOX" \
  --json \
  --output-schema "$SKILL_DIR/templates/headless-output-schema.json" \
  --output-last-message "$RUN_DIR/headless-final.json" \
  "$PROMPT" \
  > "$RUN_DIR/headless.jsonl" 2>&1
```

When `--output-schema` is unavailable, keep the same requested JSON shape and
save the last message for review. The required final fields are `status`,
`run_id`, `state_path`, `summary`, `changed_files`, `verification`,
`open_gaps`, `residual_risk`, and `next_action`.

## Required Artifacts

- `.codex-orchestrator/runs/<run_id>/headless.jsonl`
- `.codex-orchestrator/runs/<run_id>/headless-final.md` or
  `.codex-orchestrator/runs/<run_id>/headless-final.json`
- `.codex-orchestrator/runs/<run_id>/context.json`
- `.codex-orchestrator/runs/<run_id>/state.json`
- `.codex-orchestrator/runs/<run_id>/events.jsonl`
- `.codex-orchestrator/state.json` as latest-state compatibility copy/pointer
- raw verification output paths for failures

The target must not report completion until `state.json` contains
`context_snapshot_path`, `context_basis_hash`, `context_health`,
`lifecycle_outcome=finished`, and a passing `completion_audit` with non-empty
`prompt_to_artifact_checklist` and `verification_evidence`. `context_health`
must include `status`, `next_action`, and `handoff_ready`; finished targets must
be `handoff_ready=true` and not `red`. Blocked or failed targets must set a
non-success `lifecycle_outcome`, a concrete `handoff_reason`, and a
`context_health.next_action` suitable for resume.

For executable tasks, the target may record `unit_manifest` with `unit_type`,
`context_mode`, `required_skills`, `tool_policy`, `allowed_write_globs`,
`forbidden_write_globs`, `artifact_policy`, and `max_context_chars`. Finished
runs require every completed task to have a valid manifest. `implementation`
manifests must include non-empty `allowed_write_globs`; `read-only` manifests
must not allow write globs.

When a task records `unit_manifest`, the target should run or honestly
substitute `scripts/check_run_diffs.py --repo-root "$WORKTREE_ABS" --state
"$RUN_DIR/state.json" --task <task_id>` before task completion. The diff check
is post-facto policy evidence, not a low-level write hook.

The target should append project-local events with
`scripts/append_run_event.py`. The event journal is run evidence only; terminal
success still depends on `state.json`, `context_health`, and
`completion_audit`. Finished state must include matching `event_journal_path`
and a positive `last_event_seq`.

Before claiming terminal success, run `scripts/reconcile_state.py --check` or
`--repair-safe`. If blocking drift remains, the target must report a blocked or
failed lifecycle outcome with a concrete resume action instead of
`lifecycle_outcome=finished`.

When a headless target records required phase methods, it must use
`method_audit` evidence instead of skill-invocation intent. Implementation TDD
needs RED and GREEN evidence references, review needs findings or an explicit
no-findings residual-risk statement, and completion verification needs
`completion_audit.verification_evidence`. Docs-only or read-only analysis runs
may waive implementation methods only with an explicit reason.

## Learning Log

Headless artifacts remain under `.codex-orchestrator/runs/<run_id>/`. Learning
events are separate user-local records written to:

```text
~/.codex/learning/kws-codex-plan-executor/runs/<YYYY-MM-DD>/<run_id>/events.jsonl
```

Use `references/learning-log.md` and `scripts/append_learning_event.py` for
`init-run`, `append`, and `close-run` around `blocker`, `error`,
`verification_failure`, `recurring_issue`,
`successful_workaround`, and actionable `completion_learning` events. `prompt`
and `handoff` are not logging modes.

## Sandbox Selection

`headless_sandbox=workspace-write` is the default for implementation runs.
`headless_sandbox=read-only` is only for preflight, parse, or prompt
verification. If a read-only headless run reaches a task that requires editing,
stop with a blocker instead of silently switching sandbox mode.

## Eval Harness Boundary

When the outer eval harness invokes headless mode, it runs
`evals/check_execution.py` after the target execution finishes. The target
execution must not inspect fixture YAML, baseline files, `.harness` metadata,
or expected values. Use only the plan/spec/docs, state file, skill references,
and project files available in the test worktree.

## Hard Rule

Do not use `--dangerously-bypass-approvals-and-sandbox` unless the user
explicitly requested it and the run target is an isolated throwaway repository
or CI sandbox.
