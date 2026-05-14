# Architecture - kws-codex-plan-executor

Runtime instructions live in `SKILL.md`. This file records the stable design.

## Purpose

`kws-codex-plan-executor` is the forward Codex-native entrypoint for plan
execution and prompt export. It fully replaces the former
`kws-new-session-plan-prompt-gpt-5-5` compatibility entrypoint.

## Modes

- `interactive`: default, current-session execution with visible progress,
  implemented inside a dedicated `codex/...` git worktree.
- `headless`: explicit `codex exec` run for eval, CI, or detached execution,
  launched only after a dedicated `codex/...` git worktree exists.
- `prompt`: legacy fresh-session prompt export.
- `handoff`: continuation prompt export for resuming an existing run.

## Runtime Flow

1. Resolve paths and mode.
2. Validate plan structure with `scripts/parse_plan.py` for execution modes.
3. Create or select a dedicated non-conflicting `codex/...` git worktree.
4. Initialize a `run_id` and update `.codex-orchestrator/runs/<run_id>/state.json`.
5. Build `.codex-orchestrator/runs/<run_id>/context.json` and store
   `context_snapshot_path` plus `context_basis_hash`.
6. Initialize and refresh `context_health` at semantic boundaries.
7. Record a task execution contract before edits.
8. Execute tasks locally unless subagents were explicitly requested.
9. Verify each task with risk-scaled commands and record failures with stable
   `ISSUE_KEY` values.
10. Record optional carried acceptance and method audit evidence when a task
    carries sequential metrics or declares required phase methods.
11. Write `completion_audit` and terminal `lifecycle_outcome`.
12. Validate state and summarize changed files, verification, resources, and
   residual risk.

## Worktree Isolation Contract

Execution modes never implement from `main` or from the caller's original
checkout. A new run creates a dedicated non-conflicting `codex/...` git
worktree before any task contract or edits. The executor checks
`git worktree list --porcelain` and local branches before choosing a
branch/path. If the preferred branch name already exists or the path is already
claimed, the executor appends the run id or another unique pre-run suffix and
records the final branch/worktree in state.

Resume may select the worktree stored in an explicit state path or run id. If
that worktree is missing or no longer matches the stored branch, execution
blocks rather than silently falling back to the original checkout.

## State File Contract

`.codex-orchestrator/runs/<run_id>/state.json` is the source of truth for
resuming one execution. `.codex-orchestrator/state.json` is retained only as a
latest-state compatibility copy or pointer. The schema is documented in
`references/state-schema.md` and mechanically checked by
`scripts/validate_state.py`.

Execution runs also write `.codex-orchestrator/runs/<run_id>/context.json`.
The snapshot records the plan/spec/docs source list and source hashes; the
state file records `context_snapshot_path` and `context_basis_hash` so resume
and handoff do not rely on implicit session memory.

`context_health` is the compact resumability signal inside state. It is updated
after the context snapshot, after task boundaries, after blocker/error events,
before handoff/resume, and before final completion. It records
`status=green|yellow|red`, `next_action`, `open_questions`,
`known_assumptions`, and `handoff_ready` so future agents can tell whether the
run can continue from artifacts rather than hidden chat context. Whenever
`context_health` changes, `context_health.last_checked_at` changes in the same
state write. Finished outcomes require that timestamp to be present and not
older than `timestamps.updated_at`.

`current_phase` describes internal progress. `lifecycle_outcome` describes the
terminal handoff result: `finished`, `blocked`, `failed`, `userinterlude`, or
`askuserQuestion`. Finished outcomes require a passing `completion_audit` with
`prompt_to_artifact_checklist` and `verification_evidence`; non-success
outcomes require `handoff_reason`. Finished outcomes also require
`context_health.handoff_ready=true` and a non-red context health status.

Task entries may include `carried_acceptance` for sequential acceptance metrics
that cannot be resolved until a later task. Open carried acceptance is allowed
while execution continues, but finished runs must resolve or explicitly accept
the carried criterion and cite final metric evidence.

Top-level `method_audit` can record required phase methods as evidence-backed
`applied`, `missing`, or `waived` entries. The validator checks declared
methods such as TDD, review, completion verification, and the superpowers gate
against evidence references rather than skill-invocation intent.

Plans may include optional task dependencies via visible `Depends on:` lines.
`scripts/parse_plan.py` validates known dependency references and cycle-free
dependencies, then emits `depends_on` metadata. This metadata is advisory only
and does not replace task contracts.

## Learning Log Contract

Execution modes may append redacted notable-boundary events to a user-local
per-run log:

```text
~/.codex/learning/kws-codex-plan-executor/
  index.jsonl
  runs/<YYYY-MM-DD>/<run_id>/{meta.json,events.jsonl,final.json}
```

`run_id` is generated from UTC time, repo slug, branch slug, head hash, and a
random suffix. The helper lifecycle is `init-run`, `append`, and `close-run`.
Events include `run_id`, `execution.run_dir`, and `execution.state_path` so logs
from multiple projects or multiple same-project executors remain queryable and
do not logically mix. This log is for improving the executor across
repositories. It does not replace per-run state, checkpoints, headless logs, or
raw verification artifacts.

`index.jsonl` is a start index. Health is resolved from terminal `final.json`
when present, then project-local state, then learning-log metadata. New run
metadata writes `helper_pid` while retaining legacy `pid`; both identify the
short-lived helper process, not the durable Codex executor session. The
read-only `scripts/check_learning_log_health.py` reporter summarizes recent
runs, treats zero-event success as normal, reports append-only index mismatch
as informational, includes project-state and git-state summaries when
available, and reports `stale_candidate` only from inactive project state rather
than helper-pid liveness.

## Subagent Policy

Subagents are opt-in only. The executor may use `spawn_agent` only when the user
explicitly asks for subagents, delegation, parallel work, or passes
`subagents=on`. Otherwise implementation, review, and verification are local to
the current Codex session.

## Headless Codex Exec Contract

Headless mode first creates a dedicated worktree, then uses
`codex exec --json --output-last-message`, creates
`.codex-orchestrator/runs/<run_id>/` before redirecting logs, and defaults to
`--sandbox workspace-write`. `headless_sandbox=read-only` is limited to
preflight, parse, and prompt verification; implementation tasks stop instead of
silently switching sandbox mode. Headless mode may use `--output-schema` for
structured final results. It does not use
`--dangerously-bypass-approvals-and-sandbox` unless the user explicitly asks and
the target is isolated.

TDD is an execution-mode invariant, not a headless-only rule. Both interactive
and headless implementation work must pass through `using-superpowers` and
`test-driven-development` before feature, bugfix, refactor, or behavior-change
implementation. Headless runs are fresh Codex processes, so their prompts must
bootstrap those skills explicitly rather than relying on parent-session state.
Execution docs also cover local environment preflight, verification resource
serialization, Docker/Gradle resource triage, and React Router lazy-route test
harness scope so common environment failures are not misclassified as source
changes.

The supervising session owns the `codex exec` launch. Once the target process
starts, `mode=headless` means it writes headless artifacts while executing
locally; it must not recurse into another nested `codex exec`.

The eval harness creates real headless worktrees for resume and dirty-worktree
scenarios. `initial_state` is written before the bootstrap commit, while
`dirty_files` are written after the commit so `git status` exposes them as user
dirty work. The target run is forbidden from reading fixture YAML, baselines,
`.harness` metadata, or expected values; the outer harness performs final
fixture checks.

## Prompt Export Compatibility

Prompt export mode copies the old prompt-generator template behavior:
verified absolute paths, prompt-only output, conservative Spark evidence
packing, no-Spark removal, continuation ledger handling, risk-scaled
verification, and session-owned cleanup boundaries.

Fresh-session prompts mirror the runtime source-grounding and completion-proof
contracts: create `context.json` before edits, report `lifecycle_outcome`, and
finish only with healthy `context_health` and a passing `completion_audit`.

## Eval Surface

Deterministic scripts own mechanical correctness:

- `scripts/parse_plan.py`
- `scripts/validate_state.py`
- `scripts/check_learning_log_health.py`
- `evals/check_prompt.py`
- `evals/check_execution.py`
- `evals/check_parse_plan.py`
- `evals/check_state_schema.py`
- `evals/check_learning_log.py`
- `evals/check_skill_contract.py`

`evals/judge.md` is reserved for subjective quality after deterministic checks.

Dynamic execution fixtures now cover:

- `resume=latest` preferring persisted state over a conflicting plan.
- unrelated dirty worktree files being preserved while execution continues.
- related dirty task files blocking before edits.
- interactive success runs recording the task execution contract in state.

## Migration From Legacy Prompt Export

The old `kws-new-session-plan-prompt-gpt-5-5` skill has been removed from the
package. Prompt export usage should call `kws-codex-plan-executor mode=prompt`.
