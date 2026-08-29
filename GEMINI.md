# GEMINI.md - Archive

Read `AGENTS.md` first. This file only adds Gemini-specific notes.

- Active code: `apps/cli/`, `apps/api/`, `apps/console/`,
  `packages/orchestrator/`, `packages/runway-control/`,
  `packages/provider-adapters/`, `packages/lens-store/`,
  `packages/lens-projectors/`, `native/kernel/`.
- Do not recreate `components/agentlens`.
- Keep `.waygent/`, `.agentlens/`, `.claude/`, `.codex-orchestrator/`, and
  `.orchestrator/` out of git.
- Default run root is platform-specific. See
  `docs/operations/state-root-migration.md`.
- Use the smallest check that proves the change, and report the command.
