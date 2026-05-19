---
name: kws-codex-plan-executor
description: Use when executing an implementation plan in Codex from a plan path and optional spec/design docs, or when exporting a fresh-session/handoff prompt from the same plan.
metadata:
  version: "2.19.1"
  updated_at: "2026-05-19"
---

# KWS Codex Plan Executor

## Overview

Execute implementation plans in Codex or export a paste-ready prompt from the
same inputs.

Default behavior is interactive execution in the current Codex session, with
implementation isolated in a dedicated non-conflicting git worktree under
`~/.codex/worktrees/`. Runtime state, hooks, learning event payloads, and other
orchestration-only artifacts live under `~/.codex/orchestrator/`.

## Invocation

Supported arguments:

- `plan=<abs-or-repo-relative-path>` required except resume-only flows.
- `spec=<path>` optional.
- `docs=<path1,path2>` optional.
- `workspace=<path>` optional.
- `resume=latest|<state-path>|<run_id>` optional; if multiple candidate active
  runs exist, stop and ask which run/state to resume.
- `mode=interactive|headless|prompt|handoff` optional, default `interactive`.
- `subagents=auto|on|off` optional, default `auto`; `subagents=on`
  explicitly permits subagents for this run, and `subagents=off` forces a
  local-only run.
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

## Hard Boundary

Do not use `--dangerously-bypass-approvals-and-sandbox` unless the user
explicitly requests it and the target is an isolated throwaway repo or CI
sandbox.

Execution modes must not implement from `main` or the caller's original
checkout. If a dedicated non-conflicting worktree under `~/.codex/worktrees/`
cannot be created or selected before task contracts and edits, stop with a
blocker.

Only use `spawn_agent` when the user explicitly requests subagents,
delegation, or parallel agent work, or passes `subagents=on`. Do not spawn
subagents when `subagents=auto` without an explicit user request, or when
`subagents=off`.

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
- Successful terminal runs set `lifecycle_outcome=finished` and include a
  passing `completion_audit` with `prompt_to_artifact_checklist` and
  `verification_evidence`.
- Before terminal `lifecycle_outcome=finished`, run drift reconciliation with
  `scripts/reconcile_state.py --check`; use `--repair-safe` only when a safe
  repair should be persisted. Unresolved blocking drift prevents a finished
  outcome.
- Blocked or failed terminal runs set a non-success `lifecycle_outcome` and a
  concrete `handoff_reason`.
- New execution state records `subagents_requested=false` by default.
  Record `subagents_requested=true` only when the user explicitly requested
  subagents/delegation/parallel work or passed `subagents=on`. Finished runs
  cannot retain running or unreviewed subagent records.
- Command observations classify bounded command evidence before root cause is
  assigned. Finished runs with `category=unknown` observations must mention the
  command in `completion_audit.residual_risk`.
- In interactive and headless execution, feature, bugfix, refactor, or
  behavior-change implementation must invoke `using-superpowers` as the skill
  gate and `test-driven-development` before implementation code. This is not a
  headless-only rule; headless only needs extra prompt bootstrap because it is a
  fresh `codex exec` process. Record RED evidence before implementing, then
  GREEN evidence after the fix.
- Headless `codex exec` prompts must bootstrap applicable skills because parent
  session skill state is not assumed to carry over. Explicitly include
  `using-superpowers` and `test-driven-development` for implementation work.
- Headless final output follows the structured result shape documented in
  `templates/headless-output-schema.json` when schema output is available.

## Workflow

1. Resolve and verify paths. Prefer explicit paths; infer only when one
   workspace and one plan are unambiguous.
2. Select mode. Read `references/mode-contracts.md` if behavior is not obvious.
3. For `prompt` or `handoff`, use `templates/fresh-session-prompt.txt` and
   `references/prompt-export-checklist.md`.
4. For `interactive`, follow `references/execution-cycle.md`.
5. For `headless`, follow `references/headless-runner.md`.
6. Maintain `~/.codex/orchestrator/<run_id>/state.json` using
   `references/state-schema.md`; keep repository worktrees free of executor
   runtime artifacts.
7. Build `context.json` for execution modes before edits, maintain
   `context_health`, and record completion proof before reporting a finished
   lifecycle outcome.
8. For execution modes, record notable-boundary learning events using
   `references/learning-log.md`.
9. Validate using scripts before claiming completion.

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
3. Keep conservative Spark evidence packing unless the user requests no Spark,
   no model optimization, or `gpt-5.5 only`.
4. Include `templates/spark-scout-bullets.ko.txt` only when the user explicitly
   asks for broader Spark/model scout routing.
5. Run the checklist in `references/prompt-export-checklist.md`.

Prompt and handoff modes are export-only. Do not create `~/.codex/orchestrator`
artifacts, create worktrees, execute tasks, or report completion artifacts in
these modes. Return exactly one fenced `text` block containing the generated
prompt. Handoff export must include the literal `HANDOFF CHECKPOINT`; no-Spark
or `gpt-5.5 only` exports must still include the literal `gpt-5.5 high` while
omitting Spark routes.

## Validation Matrix

| Mode | Required checks before completion |
|------|-----------------------------------|
| `interactive` | `scripts/parse_plan.py`, `context.json`, `context_health`, changed-project tests or honest substitute, passing `completion_audit` for `lifecycle_outcome=finished`, `scripts/validate_state.py` |
| `headless` | `scripts/parse_plan.py`, `context.json`, `context_health`, acceptance command or honest substitute, passing `completion_audit` for `lifecycle_outcome=finished`, `scripts/validate_state.py`, headless JSONL/final artifact review |
| `prompt` | `evals/check_prompt.py` or the prompt export checklist when no fixture exists |
| `handoff` | `evals/check_prompt.py` or the prompt export checklist, plus source state/path readability |

## Maintenance

Use `references/change-protocol.md` before editing this skill. Update
`HISTORY.md`, `ARCHITECTURE.md`, package metadata, and eval baselines for
behavior changes.

For eval harness runs, the outer harness runs `evals/check_execution.py`. The
target executor must not inspect fixture YAML, baseline files, `.harness`
metadata, or expected values.
