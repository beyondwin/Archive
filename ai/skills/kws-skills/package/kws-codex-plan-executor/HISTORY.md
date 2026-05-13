# Skill History - kws-codex-plan-executor

Source of truth for current behavior: `SKILL.md`, `templates/`, and
`references/`. This file tracks release intent and migration history.

## v1.0.0 - Initial Codex executor and prompt-export replacement (2026-05-13)

- Introduced a Codex-native plan executor with interactive, headless, prompt,
  and handoff modes.
- Migrated the fresh-session prompt generator contract into `mode=prompt`.
- Added deterministic parsing, state validation, and eval harness structure.
- Kept `kws-new-session-plan-prompt-gpt-5-5` as a temporary deprecated wrapper.
