# Skill History - kws-codex-plan-executor

Source of truth for current behavior: `SKILL.md`, `templates/`, and
`references/`. This file tracks release intent and migration history.

## v1.8.0 - Harden learning-log health and execution evidence (2026-05-14)

- Added `scripts/check_learning_log_health.py` as a read-only reporter that
  resolves terminal outcomes from `final.json`, treats zero-event success as
  routine, and reports old unclosed dead-pid runs as diagnostic `stale`.
- Extended learning-log evals with fixtures for final/index mismatch,
  zero-event success, stale dead-pid runs, and live unclosed runs.
- Added carried acceptance validation so finished runs cannot leave sequential
  metrics open without final evidence.
- Added method audit validation for declared required phase methods, including
  RED/GREEN TDD evidence, review findings or residual-risk evidence, and
  completion verification evidence.
- Documented local environment preflight, verification resource-key
  serialization, Docker/Gradle resource triage, and React Router lazy-route
  verification risks.

## v1.7.1 - Clarify TDD scope across execution modes (2026-05-14)

- Clarified that `test-driven-development` is required for implementation work
  in both `interactive` and `headless` execution; it is not a headless-only
  rule.
- Added per-task `using-superpowers` and `test-driven-development` skill gates
  to `references/execution-cycle.md`, including RED/GREEN evidence recording.
- Updated `templates/fresh-session-prompt.txt` and
  `references/headless-runner.md` to distinguish transport bootstrap from TDD
  applicability.
- Added deterministic contract checks for this distinction.

## v1.7.0 - Require dedicated execution worktrees (2026-05-14)

- Made `interactive` and `headless` execution require a dedicated
  non-conflicting `codex/...` git worktree before any task contract or edits.
- Forbid implementation from `main` or the caller's original checkout during
  execution modes.
- Added deterministic contract checks for mandatory worktree isolation,
  branch/path uniqueness, and no-main implementation language across runtime
  references and prompt export.

## v1.6.0 - Track context health in execution state (2026-05-14)

- Added `context_health` to execution state so agents can record whether a run
  is resumable from durable artifacts instead of hidden chat context.
- Required execution modes after preflight to validate `context_health` shape,
  status, `next_action`, and `handoff_ready` semantics.
- Updated runtime docs, prompt export, state schema, deterministic evals, and
  human-facing Korean guide around context-health boundaries.

## Docs-only - Korean human guide (2026-05-14)

- Added `docs/user-guide.ko.md` as a Korean human-facing guide for usage,
  structure, execution artifacts, operating rationale, maintenance, and common
  blockers.
- Kept `SKILL.md` unchanged so the agent-facing runtime contract remains
  compact and optimized for execution.
- Linked the guide from `README.md`; no runtime behavior, prompt export,
  scripts, evals, or public skill metadata changed.

## v1.5.0 - Add source-grounded completion proof (2026-05-14)

- Hardened plan parsing to ignore hidden Markdown regions such as fenced code,
  HTML comments, and indented code.
- Added per-run `context.json` source snapshots with source hashes.
- Added terminal `lifecycle_outcome` metadata and completion audit proof for
  successful runs.
- Added optional execution dependency metadata and high-risk verification
  matrix guidance without changing subagent opt-in policy.

## v1.4.0 - Shard Codex executor runs by run_id (2026-05-13)

- Replaced the single global Codex learning log with per-run user-local
  directories under
  `~/.codex/learning/kws-codex-plan-executor/runs/<date>/<run_id>/` plus
  `index.jsonl`.
- Extended `scripts/append_learning_event.py` with `init-run`, `append`, and
  `close-run`, and required events to carry `run_id`, `run_dir`, and
  `state_path`.
- Moved primary project-local state/artifacts to
  `.codex-orchestrator/runs/<run_id>/`, keeping `.codex-orchestrator/state.json`
  only as a latest-state compatibility copy or pointer.
- Updated deterministic evals to reject cross-run event leakage and invalid
  per-run state paths.

## v1.3.1 - Bootstrap process skills in headless runs (2026-05-13)

- Required headless prompts and eval runs to bootstrap applicable installed
  skills instead of assuming parent-session skill state carries over.
- Explicitly named `using-superpowers` and `test-driven-development` in
  headless runtime contracts and deterministic contract checks.
- Clarified that the supervising session launches `codex exec`; the headless
  target process must not recursively launch another nested `codex exec`.

## v1.3.0 - Add execution learning log helper (2026-05-13)

- Added user-local JSONL learning events for `interactive` and `headless`
  execution notable boundaries.
- Added `scripts/append_learning_event.py` to validate, redact, and append
  learning events outside project repositories.
- Added `references/learning-log.md` and deterministic helper checks.
- Aligned runtime instructions, headless docs, prompt export, and contract evals
  around execution-only learning logs.

## v1.2.1 - Align prompt export and state validation contracts (2026-05-13)

- Aligned prompt/handoff export with the current executor contract:
  `.codex-orchestrator/state.json` is the source of truth and subagents remain
  opt-in.
- Strengthened `validate_state.py` to reject missing or incomplete task
  contracts.
- Fixed preflight ordering so plan parsing precedes dirty-file classification.
- Documented `headless_sandbox=read-only` behavior and ensured headless artifact
  directories are created before shell redirection.
- Added deterministic checks for prompt/runtime contract drift and state schema
  enforcement.

## v1.2.0 - Add dynamic headless eval fixtures (2026-05-13)

- Added actual headless fixtures for `resume=latest`, unrelated dirty
  worktree continuation, and related dirty worktree blocking.
- Required the interactive docs-only fixture to verify task contracts are
  recorded inside `.codex-orchestrator/state.json`.
- Updated the eval harness to create `initial_state` before bootstrap commits,
  create `dirty_files` after commits, and prevent fixture/baseline leakage into
  target runs.
- Allowed expected headless artifacts in `check_execution.py`.

## v1.1.0 - Add eval-gated execution safeguards (2026-05-13)

- Added deterministic contract and parser evals for resume, validation matrix,
  task-contract gating, sandbox exposure, dirty-worktree classification, and
  file-block aliases.
- Added Korean and English file-block aliases to `scripts/parse_plan.py`.
- Extended execution evals to inspect final output, run logs, blocked outcomes,
  forbidden file changes, and recorded task contracts.

## v1.0.1 - Remove legacy wrapper dependency (2026-05-13)

- Removed the `kws-new-session-plan-prompt-gpt-5-5` package entrypoint.
- Clarified that prompt export now goes directly through
  `kws-codex-plan-executor mode=prompt`.

## v1.0.0 - Initial Codex executor and prompt-export replacement (2026-05-13)

- Introduced a Codex-native plan executor with interactive, headless, prompt,
  and handoff modes.
- Migrated the fresh-session prompt generator contract into `mode=prompt`.
- Added deterministic parsing, state validation, and eval harness structure.
- Kept `kws-new-session-plan-prompt-gpt-5-5` as a temporary deprecated wrapper.
