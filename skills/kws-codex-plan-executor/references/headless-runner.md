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
RUN_ID="$(python3 "$SKILL_DIR/scripts/generate_run_id.py" \
  --repo-name "$REPO_NAME" --branch "$BRANCH" --head "$HEAD_SHA")"
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

# AgentLens is the canonical event sink (v2.18 cutover; the legacy
# append_run_event.py / append_learning_event.py helpers were removed).
# Empty ORCH_RUN_ID (CLI absent, registry error) means downstream emits no-op.
ORCH_RUN_ID="$(agentlens run-open \
  --agent kws-cpe-orchestrator \
  --workspace "$WORKTREE_ABS" \
  --meta plan="$PLAN_REL" \
  --meta spec="${SPEC_REL:-}" \
  --meta mode=headless \
  2>/dev/null || echo "")"
# Persist ORCH_RUN_ID under .codex-orchestrator/runs/$RUN_ID/state.json field
# `agentlens_orchestration_run` (string or null) at first state.json write;
# .codex-orchestrator/state.json stays as the latest-state compatibility copy.

AGENTLENS_PARENT_RUN_ID="${ORCH_RUN_ID:-}" \
codex exec \
  --cd "$WORKTREE_ABS" \
  --sandbox "$HEADLESS_SANDBOX" \
  --json \
  --output-last-message "$RUN_DIR/headless-final.md" \
  "$PROMPT" \
  > "$RUN_DIR/headless.jsonl" 2>&1
```

`generate_run_id.py` is illustrative — any deterministic helper that yields a
`<utc>-<repo-slug>-<branch-slug>-<head>-<rand>` id is acceptable, as long as
the id is reused across project-local state, headless artifacts, and every
AgentLens emit.

The child `codex exec` reads `AGENTLENS_PARENT_RUN_ID` from its environment and
exports it as `ORCH_RUN_ID` for all emit-site code so events publish into the
same AgentLens orchestration run as the supervisor. If `ORCH_RUN_ID` is empty,
every guarded `agentlens event append` becomes a silent no-op.

## Schema Output Variant

```bash
RUN_ID="$(python3 "$SKILL_DIR/scripts/generate_run_id.py" \
  --repo-name "$REPO_NAME" --branch "$BRANCH" --head "$HEAD_SHA")"
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

ORCH_RUN_ID="$(agentlens run-open \
  --agent kws-cpe-orchestrator \
  --workspace "$WORKTREE_ABS" \
  --meta plan="$PLAN_REL" \
  --meta spec="${SPEC_REL:-}" \
  --meta mode=headless \
  2>/dev/null || echo "")"

AGENTLENS_PARENT_RUN_ID="${ORCH_RUN_ID:-}" \
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

The target emits replay events directly to AgentLens under `kws-cpe.<event>`
(see `references/event-journal.md` for the namespace mapping). The event
stream is run evidence only; terminal success still depends on `state.json`,
`context_health`, and `completion_audit`. Read `ORCH_RUN_ID` from the
`AGENTLENS_PARENT_RUN_ID` env or from the per-run `state.json` field
`agentlens_orchestration_run`; if both are empty the emit no-ops silently:

```bash
ORCH_RUN_ID="${AGENTLENS_PARENT_RUN_ID:-$(jq -r '.agentlens_orchestration_run // ""' \
  "$RUN_DIR/state.json" 2>/dev/null)}"
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens event append --run "$ORCH_RUN_ID" \
    --type kws-cpe.<event> \
    --payload-json '<json>' \
    2>/dev/null || true
fi
```

The first state.json write must persist `agentlens_orchestration_run` (the
supervisor-captured `ORCH_RUN_ID` or `null`). The legacy
`scripts/append_run_event.py` helper was removed at the v2.18 cutover.

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

When a command result needs triage before root cause is assigned, the target may
record `command_observations[]` in state. Each observation needs command,
status, taxonomy category, bounded evidence, and next action. Use
`category=unknown` only with bounded evidence, and mention the command in
`completion_audit.residual_risk` before any finished outcome.

## Learning Log

Headless artifacts remain under `.codex-orchestrator/runs/<run_id>/`. Learning
events are recorded directly to AgentLens under the
`kws-cpe.learning.<event>` namespace per `references/learning-log.md`. Cover
`blocker`, `error`, `verification_failure`, `recurring_issue`,
`successful_workaround`, and actionable `completion_learning` events. `prompt`
and `handoff` are not logging modes.

Emit when `ORCH_RUN_ID` is non-empty (e.g.
`kws-cpe.learning.successful_workaround`,
`kws-cpe.learning.verification_failure`); failures are silent. The legacy
`scripts/append_learning_event.py` helper was removed at the v2.18 cutover —
AgentLens is now the sole sink for these events. Historical
`~/.codex/learning/kws-codex-plan-executor/` archives remain on disk but are
no longer written by this skill.

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
