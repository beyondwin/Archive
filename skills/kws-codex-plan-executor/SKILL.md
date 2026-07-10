---
name: kws-codex-plan-executor
description: Use when executing an implementation plan in Codex from a plan path and optional spec/design docs, or when exporting a fresh-session/handoff prompt from the same plan.
metadata:
  version: "3.0.0"
  updated_at: "2026-07-10"
---

# KWS Codex Plan Executor

## Overview

Execute implementation plans in Codex or export a paste-ready prompt from the
same inputs.

Default behavior is interactive execution in the current Codex session, with
implementation isolated in a dedicated non-conflicting git worktree under
`~/.codex/worktrees/`. Runtime state, hooks, learning event payloads, and other
orchestration-only artifacts live under `~/.codex/orchestrator/`.

When the current Superpowers workflow is available, CPE is a thin stateful
bridge rather than a competing implementation loop. For approved interactive
implementation plans, first run
`scripts/audit_superpowers_compatibility.py` and prefer the current
Superpowers-native execution loop when it recommends
`thin_stateful_bridge`. CPE still owns prompt and handoff export, headless
execution, resume and inspection, state artifacts, task packets, prompt cache
audits, Graphify evidence, and fallback when required Superpowers contracts are
not available.

## Invocation

Supported arguments:

- `plan=<abs-or-repo-relative-path>` required except resume-only flows.
- `spec=<path>` optional.
- `docs=<path1,path2>` optional.
- `workspace=<path>` optional.
- `resume=latest|<state-path>|<run_id>` optional; if multiple candidate active
  runs exist, stop and ask which run/state to resume.
- `mode=interactive|headless|prompt|handoff` optional, default `interactive`.
- `subagents=auto|on|off` optional, default `on`; `subagents=on` is the
  adaptive subagent-first default for eligible executable tasks, `subagents=off`
  forces a local-only run, and `subagents=auto` uses conservative spawning only
  when the user explicitly requested subagents, delegation, or parallel work.
- `headless_sandbox=workspace-write|read-only` optional, default
  `workspace-write`; `read-only` is for preflight/prompt verification and
  blocks edit execution.
- `context_mode=auto|sliced|full` optional, default `auto`; `auto` uses task
  packets when a spec exists.
- `context_budget=<positive-int>` optional, default `60000` per task packet.
- `context_threshold=<float>` optional, default `0.70`; values must be in
  `[0.05,0.95]`.
- `manifest_fallback=full_spec_on_blocker|halt_on_blocker` optional, default
  `full_spec_on_blocker`.
- Natural-language hints are accepted only after deterministic parser
  resolution; print the parsed echo line before preflight.

## Superpowers Compatibility

Before choosing an interactive execution route for an approved implementation
plan, run:

```bash
python3 scripts/audit_superpowers_compatibility.py \
  --superpowers-root "$SUPERPOWERS_ROOT" \
  --skill-root "$CPE_SKILL_ROOT"
```

Use the current installed Superpowers root from the active skill registry or
session metadata. If the audit passes and recommends `thin_stateful_bridge`,
use Superpowers `subagent-driven-development` as the implementation loop while
preserving CPE's run state, task packets, worktree boundary, validation, and
completion audit evidence. If the audit fails, do not guess at compatibility:
continue with the existing CPE execution cycle or stop with a blocker when the
requested mode depends on missing Superpowers contracts.

Prompt, handoff, headless, resume, and inspection remain CPE-owned modes. The
compatibility audit is read-only and must not create worktrees, mutate state, or
execute plan tasks.

## Hard Boundary

Do not use `--dangerously-bypass-approvals-and-sandbox` unless the user
explicitly requests it and the target is an isolated throwaway repo or CI
sandbox.

Execution modes must not implement from `main` or the caller's original
checkout. If a dedicated non-conflicting worktree under `~/.codex/worktrees/`
cannot be created or selected before task contracts and edits, stop with a
blocker.

Use `spawn_agent` for eligible executable tasks when the resolved invocation has
`subagents=on` and deterministic adaptive dispatch says delegation has value.
`subagents=on` remains the subagent-first default and means subagents are
allowed and preferred when the task is parallel-worthy, independently scoped,
and safe to delegate. Use `spawn_agent` for `subagents=auto` only when the user
explicitly requested subagents, delegation, or parallel agent work. Do not spawn
subagents when `subagents=auto` without an explicit user request, when
`subagents=auto` lacks explicit delegation intent, when `subagents=off`, or when
`scripts/preflight_dispatch.py` selects `local_fallback` for an adaptive local
fast path.

When dispatching subagents, use task packets, not raw full-plan context. Do not
ask a subagent to infer its write scope from the entire plan.
If an otherwise executable task falls back to local implementation under
`subagents=on`, record the failed pre-dispatch prerequisite or concrete reason
in the task `subagent_strategy`. The main agent remains responsible for
post-diff and state review before accepting subagent output.

Subagent dispatch maintains three linked state surfaces per
`references/subagent-run-store.md`: `subagent_runs` for concrete worker records,
task `subagent_strategy` for the accepted per-task decision, and
`dispatch_decisions` plus `delegation_policy` for deterministic pre-dispatch
evidence. Keep these surfaces aligned before any finished lifecycle outcome.

## Core Invariants

- No edits before a 5-line `TASK EXECUTION CONTRACT` is stated and recorded:
  `scope`, `files_to_inspect`, `allowed_edits`, `forbidden_edits`, and
  `acceptance_command_or_honest_substitute`.
- Executable tasks may record `unit_manifest` with context, skill, tool, and
  write policy; finished runs require every completed task to have a valid
  manifest, including `allowed_write_globs` and `forbidden_write_globs`.
- For every new `interactive` or `headless` execution run, create a run id using
  `<plan-slug>-<YYYYMMDD-HHMMSS>`. Create code worktrees at
  `~/.codex/worktrees/<run_id>` and orchestration directories at
  `~/.codex/orchestrator/<run_id>`. If the worktree path already exists, append
  a short random suffix before creating it.
- The worktree contains only normal repository files and git metadata. Store
  `state.json`, `context.json`, `hooks/`, `learning_events/`, headless logs, and
  other executor artifacts under `~/.codex/orchestrator/<run_id>/`.
- Before execution, classify dirty worktree changes as `related` or
  `unrelated`. Continue past unrelated dirty files only when they are outside
  the declared task files; stop before touching related dirty files.
- Execution plans may use `Files`, `Affected files`, `Modified files`,
  `Changed files`, `수정 파일`, `변경 파일`, `대상 파일`, or `파일` headings for
  task file blocks. Execution mode still stops if no file block is present.
- Execution plans may also use fenced `yaml waygent-task` or
  `yaml agentrunway-task` blocks with `id`, `title`, `dependencies`, and
  `file_claims`; these blocks are executable task contracts and satisfy the
  file-scope requirement when their paths stay inside the repo.
- Resume mode uses an explicit state path/run id, or the only active run found
  under `~/.codex/orchestrator/`. Do not infer between multiple ambiguous active
  runs. `resume=latest` scans `~/.codex/orchestrator/*/state.json`.
- In `interactive` and `headless` execution, record execution-only redacted
  notable-boundary learning events directly to AgentLens under the
  `kws-cpe.learning.<event>` namespace per `references/learning-log.md`. Include
  `run_id`, `run_dir_ref`, and `state_path_ref` in payload metadata. These refs
  are redacted/home-relative, not absolute home paths. `prompt` and
  `handoff` are not logging modes.
- Execution runs maintain replay evidence through AgentLens events under
  `kws-cpe.<event>` per `references/event-journal.md`. State remains
  authoritative; finished state records the AgentLens orchestration run id and,
  for resume, the last AgentLens event timestamp.
- At run init the orchestrator opens an AgentLens run with
  `agentlens run-open --agent kws-cpe-orchestrator --workspace "$WORKTREE_ABS"
  --meta plan=...` and persists the returned id as
  `agentlens_orchestration_run` in
  `~/.codex/orchestrator/<run_id>/state.json`. Every AgentLens call is guarded
  by `[ -n "${ORCH_RUN_ID:-}" ]` and suffixed with `2>/dev/null || true`;
  AgentLens failures must never block plan execution.
- Execution runs record `~/.codex/orchestrator/<run_id>/context.json` before
  edits and store `context_snapshot_path` plus `context_basis_hash` in state.
- Execution runs maintain `context_health` in state at semantic boundaries:
  after context snapshot creation, after each task, after blocker/error events,
  before handoff/resume, and before final completion. It must include
  `status=green|yellow|red`, `next_action`, and `handoff_ready`.
- Task packet human views are generated derivatives of task packet JSON. They
  may be included in handoff, prompt hot-tail, and subagent task context, but
  the JSON packet and state remain authoritative.
- Completed tasks may record `next_task_summary` as a one-line hot-tail hint.
  This summary never replaces structured task status, verification evidence,
  dispatch decisions, or completion audit state.
- Successful terminal runs set `lifecycle_outcome=finished` and include a
  passing `completion_audit` with `prompt_to_artifact_checklist` and
  `verification_evidence`. Finished `completion_audit` fields are structured:
  `prompt_to_artifact_checklist`, `verification_evidence`, and
  `residual_risk` are lists so downstream inspection never treats scalar text as
  character-level evidence. `residual_risk` items may be strings or structured
  residual risk objects with `owner`, `class`, `summary`, and `blocks_release`;
  a release-blocking object cannot coexist with a passed finished completion.
- Completion audit verification evidence may include structured
  `class=verification_bundle` entries for project-level command bundles. These
  entries classify evidence and do not replace per-task acceptance commands.
- Structured residual risk classes are advisory readability metadata. They
  cannot override `completion_audit.passed`, state validation, or release
  blocker rules.
- Before terminal `lifecycle_outcome=finished`, run drift reconciliation with
  `scripts/reconcile_state.py --check`; use `--repair-safe` only when a safe
  repair should be persisted. Unresolved blocking drift prevents a finished
  outcome.
- Blocked or failed terminal runs set a non-success `lifecycle_outcome` and a
  concrete `handoff_reason`.
- New execution state records `subagents_requested=true` by default because
  `subagents=on` is the default. Record `subagents_requested=false` only when
  the run is explicitly local-only (`subagents=off`) or conservative auto mode
  without an explicit subagent/delegation/parallel request. Finished runs cannot
  retain running or unreviewed subagent records.
- For v2.20+ finished runs with `subagents_requested=true`, every completed
  write-capable task records `subagent_strategy`. `mode=delegated` must point
  to reviewed, completed, accepted `subagent_runs` owned by the same task;
  `mode=local_fallback` must include a concrete reason and no delegated run
  ids.
- Adaptive local fast path is a quality-preserving local execution decision,
  not a verification skip. It may choose `local_fallback` for small, low-risk,
  linear tasks, but the task still requires the task contract, unit manifest,
  diff-scope review, acceptance evidence, reconciliation, and state validation.
- Command observations classify bounded command evidence before root cause is
  assigned. Finished runs with `category=unknown` observations must mention the
  command in `completion_audit.residual_risk`.
- New execution runs record effective delegation policy in `delegation_policy`;
  policy fallback is deterministic evidence, not handwritten rationale.
- Local environment preflight records detection-only `preflight_bootstrap`
  suggestions and `environment_capabilities`; bootstrap commands are never run
  automatically.
- Prefer `execution_worktree` for edit and command provenance when present.
  `workspace` remains backward-compatible metadata for older state.
- Execution runs produce a read-only run readiness audit after task packet
  creation and before task contracts or edits. Readiness issues classify
  missing acceptance commands, full-spec fallback, packet context budget, and
  write-scope formatting before per-task dispatch.
- Execution runs produce a read-only plan executability audit before task
  contracts or edits. The audit records `plan_executability_audit` evidence,
  summarizes `thin_stateful_bridge` readiness, and classifies task-level
  `delegate`, `local_fast_path`, `operator_review`, or `block` fit without
  mutating worktrees, state, or repository files. Finished operational-quality
  states may distinguish raw plan audit counts from operator-reviewed effective
  counts. If effective blocker counts are lower than raw counts, the state
  records `operator_reviewed_blocking_issues` and `operator_decision`.
- CPE treats Superpowers as an external Superpowers contract: it reads and
  audits installed Superpowers skill contracts but does not modify them.
  Interactive execution supports only current Superpowers-compatible plan
  shapes; legacy plan auto-support is not provided. Plans missing the current
  `REQUIRED SUB-SKILL` header, task file scope, or other required execution
  shape are classified as `blocked_unsupported_plan_shape` and stop before task
  contracts or edits. Operator-review risks such as lockfiles, security, infra,
  and migration paths are classified separately as `operator_review_required`.
- Plan executability `subagent_reason` for `block` results must come from a
  real blocking issue using deterministic blocker priority; adaptive local fast
  path reasons must not mask `acceptance_command_missing`, missing files, broad
  write scope, unsupported plan shape, or operator-review risk.
- Finished runs with both `dispatch_decisions` and completed write-capable
  tasks must keep final `subagent_strategy` aligned with the latest dispatch
  decision for that task. If the operator intentionally overrides a stale or
  superseded dispatch reason, the task records `subagent_strategy_override`
  with `from_reason`, `to_reason`, `changed_at`, `evidence`, and
  `operator_decision`.
- Finished states that opt into `subagent_boundary_schema_version=1` require
  accepted delegated `subagent_runs` to carry `boundary_attestation` proving the
  worker operated inside `execution_worktree` and did not dirty the source
  workspace unless an explicit operator override is recorded.
- Finished states cannot present multiple final accepted subagent attempts for
  the same task/write scope; superseded attempts remain inspectable as rejected
  records with `superseded_by`.
- Read-only run inspection may compute `run_quality` for recent or stale runs
  without mutating state. Finished operational-quality states with v2.22 fields
  embed the same summary before validation.
- Read-only inspection may attach `inspection_observations` such as a finished
  missing execution worktree without rewriting durable run quality state.
- Recent-run inspection may aggregate finished states with
  `scripts/analyze_recent_runs.py`; rubric reports are derived evidence and
  never replace `state.json` or `completion_audit`.
- `run_quality.open_followups` records actionable inspection follow-ups such as
  `stale_non_terminal_run`, `missing_execution_worktree`, and schema drift; do
  not rely on a bare stale boolean when deciding resume or cleanup work.
- Finished operational-quality `run_quality.open_followups` records stable
  non-blocking executor debt signals: `agentlens_missing`,
  `missing_execution_worktree`, `readiness_fixable_issues`,
  `full_spec_fallback_present`, `delegation_policy_expected_local_fallback`,
  `delegation_policy_prevented_all_delegation`, and
  `delegation_policy_missing_dispatch_evidence`. Expected local fallback caused
  by an explicit-request-required spawn policy is recorded separately from
  prevented delegation. Do not report
  `delegation_policy_prevented_all_delegation` when local fallback was the
  resolved policy before execution. `completion_audit.passed=true` and
  `run_quality.grade=yellow` may coexist when product verification passed but
  executor evidence or efficiency follow-up remains.
- Recent-run analysis separates actionable followups from informational
  followups. `green-with-info` is report-only display metadata; durable
  `state.json` run quality grades remain `green`, `yellow`, or `red`.
- Expected local fallback caused by `spawn_policy=explicit-request-required`
  and no explicit delegation request is informational policy evidence, not
  proof that task safety gates were skipped.
- When read-only inspection reports stale non-terminal runs with missing
  execution worktrees, use `scripts/repair_runs.py` to produce a dry-run repair
  plan before any operator action. The only safe mutation is explicit
  `--apply --run-id <id> --action mark-blocked-stale`, which validates before
  and after the state patch and never deletes files.
- `run_quality` may report yellow operational quality even when
  `completion_audit.passed=true`; this marks executor efficiency or evidence
  quality follow-up, not product verification failure.
- Finished operational-quality `run_quality` includes `readiness`,
  `dispatch_consistency`, `context_quality`, and `verification_quality` so
  full-spec fallback, dispatch overrides, and completion evidence quality remain
  inspectable after the execution worktree is gone.
- Full-spec fallback records a structured mapping reason and suggested
  `spec_refs`; unreviewed fallback remains operational-quality debt, while
  explicitly reviewed fallback may be context-green when the context budget is
  not red.
- Full-spec fallback evidence includes deterministic `next_action` in task
  packet mapping so plan/spec authors know how to reduce context debt in the
  next run; readiness surfaces that packet-owned field and does not replace
  task packet JSON as source of truth.
- Delegation capability may be recorded at run level when spawn policy prevents
  all task spawning; this only changes operational-debt accounting and does not
  skip local task gates.
- AgentLens status is best-effort and classified as recorded, unavailable,
  emit-failed, or not-applicable; AgentLens failure cannot block product
  verification.
- `validate_state.py` remains the public validation CLI even when validation
  logic is split across domain modules.
- Normalized CPE replay checks are deterministic eval evidence from
  `scripts/normalize_cpe_run.py`. They summarize state, audits, dispatch
  decisions, residual risk classes, and forbidden durable-log patterns without
  storing raw transcripts or full prompts.
- Prompt-generating artifacts follow `references/cache-strategy.md`. The
  stable prefix role, safety, required-skill, and output-schema content stays before
  the stable-prefix boundary; run-specific paths, task packets, timestamps, git
  status, diffs, decisions, and verification evidence stay in the hot tail.
  Run `scripts/audit_prompt_cache.py`, and finished runs cannot retain
  non-empty `prompt_audit.dynamic_marker_violations`.
- Graphify-aware repositories record `graphify_audit` evidence using
  `scripts/check_graphify_freshness.py`. If `graphify update .` is required
  after code or meaningful documentation-structure changes, the completion
  audit records whether the command ran and whether tracked or ignored outputs
  changed.
- Finished runs with `graphify_audit` must also reference that evidence from
  `completion_audit.verification_evidence`; a detached Graphify audit JSON is
  not enough completion proof.
- Subagent pre-dispatch decisions use `scripts/preflight_dispatch.py` before
  spawning for eligible write-capable tasks. The adaptive decision is one of
  `delegate`, `local_fallback`, or `block`; adaptive `local_fallback` reasons
  flow into task `subagent_strategy.reason`, and `dispatch_decisions` with
  `block` cannot be carried into a finished lifecycle outcome.
- When spawn policy prevents actual delegation, pre-dispatch may record
  advisory `would_have_decision`, `would_have_reason`, and
  `would_have_value_gate` under `delegation_policy`; these fields never
  authorize spawning and never replace the final `decision`.
- In interactive and headless execution, feature, bugfix, refactor, or
  behavior-change implementation must invoke `using-superpowers` as the skill
  gate and `test-driven-development` before implementation code. This is not a
  headless-only rule; headless only needs extra prompt bootstrap because it is a
  fresh `codex exec` process. Record RED evidence before implementing, then
  GREEN evidence after the fix.
- Resolve skill paths from the active skill registry/root mapping before
  reading local `SKILL.md` files manually. Do not hard-code `.system` or any
  other skill root. If a skill path read fails, re-check the active registry
  entry and root table before diagnosing the cause; classify it as an operator
  path-resolution error unless the registry entry itself is proven stale.
- When repository instructions mention graphify, read
  `graphify-out/GRAPH_REPORT.md`, compare its `Built from commit` value with
  `git rev-parse HEAD`, run `graphify update .` after code changes, and record
  the outcome in `completion_audit.verification_evidence`. If `graphify-out/`
  is ignored, record that the update ran but generated outputs were not tracked.
- Headless `codex exec` prompts must bootstrap applicable skills because parent
  session skill state is not assumed to carry over. Explicitly include
  `using-superpowers` and `test-driven-development` for implementation work.
- Headless final output follows the structured result shape documented in
  `templates/headless-output-schema.json` when schema output is available.

## Workflow

1. Resolve and verify paths. Prefer explicit paths; infer only when one
   workspace and one plan are unambiguous.
2. Select mode. Read `references/mode-contracts.md` if behavior is not obvious.
3. For interactive implementation with current Superpowers available, run the
   Superpowers compatibility audit and use the recommended route.
4. Before task contracts or edits, run `scripts/audit_plan_executability.py`
   against parsed plan JSON and generated task packets when present. Store the
   JSON under the run directory and copy its summary into state as
   `plan_executability_audit`. If `parse_plan.py` fails in execution mode, treat
   the plan as `blocked_unsupported_plan_shape`; do not infer missing task
   files or legacy shape from raw prose.
5. For `prompt` or `handoff`, use `templates/fresh-session-prompt.txt` and
   `references/prompt-export-checklist.md`.
6. For `interactive`, follow `references/execution-cycle.md`.
7. For `headless`, follow `references/headless-runner.md`.
8. Before subagent dispatch, review `references/pre-dispatch-pipeline.md` and
   `references/subagent-run-store.md`; after dispatch, reconcile
   `subagent_runs`, task `subagent_strategy`, `dispatch_decisions`, and
   `delegation_policy`.
9. Maintain `~/.codex/orchestrator/<run_id>/state.json` using
   `references/state-schema.md`; keep repository worktrees free of executor
   runtime artifacts.
10. Build `context.json` for execution modes before edits, maintain
   `context_health`, and record completion proof before reporting a finished
   lifecycle outcome.
11. For execution modes, record notable-boundary learning events using
   `references/learning-log.md`.
12. Validate using scripts before claiming completion.

## Stop Rules

- Missing or unreadable plan: ask one short question or report blocker.
- Dirty worktree with related ambiguity: stop and report.
- Missing or unusable dedicated execution worktree: stop and report.
- Ambiguous `resume=latest` with multiple state files: stop and ask.
- Missing `Files:` blocks in execution mode: stop before edits.
- Unclear acceptance criteria on mid/high risk tasks: stop for clarification
  unless the plan gives an honest substitute.
- Verification failure without root cause after 3 same-root retries: stop with
  checkpoint.

## Prompt Export

For prompt/handoff mode:

1. Verify workspace, plan, spec, and docs paths before inserting them.
2. Fill every `{{...}}` token in `templates/fresh-session-prompt.txt` or remove
   the optional section.
3. Use only the fixed Sol/high core and Terra/high read-only scout routes.
5. Run the checklist in `references/prompt-export-checklist.md`.

Prompt and handoff modes are export-only. Do not create `~/.codex/orchestrator`
artifacts, create worktrees, execute tasks, or report completion artifacts in
these modes. Return exactly one fenced `text` block containing the generated prompt.
Handoff export includes the literal `HANDOFF CHECKPOINT` marker.

## Validation Matrix

| Mode | Required checks before completion |
|------|-----------------------------------|
| `interactive` | Superpowers compatibility audit when current Superpowers skills are available, `scripts/parse_plan.py`, `context.json`, `context_health`, plan executability audit, task packet human view evidence when generated, markdown golden-case evals when policy cases change, verification bundle evidence when project-level bundles are used, changed-project tests or honest substitute, prompt cache audit, normalized CPE replay eval when replay behavior changed, Graphify audit when applicable, dispatch decision evidence for write-capable subagent tasks, passing `completion_audit` for `lifecycle_outcome=finished`, `scripts/validate_state.py` |
| `headless` | `scripts/parse_plan.py`, `context.json`, `context_health`, task packet human view evidence when generated, markdown golden-case evals when policy cases change, verification bundle evidence when project-level bundles are used, acceptance command or honest substitute, prompt cache audit, Graphify audit when applicable, dispatch decision evidence for write-capable subagent tasks, passing `completion_audit` for `lifecycle_outcome=finished`, `scripts/validate_state.py`, headless JSONL/final artifact review |
| `prompt` | `evals/check_prompt.py` or the prompt export checklist when no fixture exists |
| `handoff` | `evals/check_prompt.py` or the prompt export checklist, plus source state/path readability |

## Maintenance

Use `docs/release-process.md` and `docs/doc-update-protocol.md` before editing
this skill. Update `HISTORY.md`, `ARCHITECTURE.md`, package metadata,
compatibility docs, and eval baselines for behavior changes.

For eval harness runs, the outer harness runs `evals/check_execution.py`. The
target executor must not inspect fixture YAML, baseline files, `.harness`
metadata, or expected values.
