# Skill History - kws-codex-plan-executor

Source of truth for current behavior: `SKILL.md`, `templates/`, and
`references/`. This file tracks release intent and migration history.

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
