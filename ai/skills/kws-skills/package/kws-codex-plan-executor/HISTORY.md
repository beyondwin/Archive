# Skill History - kws-codex-plan-executor

Source of truth for current behavior: `SKILL.md`, `templates/`, and
`references/`. This file tracks release intent and migration history.

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
