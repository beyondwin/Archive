# GEMINI.md - Archive

Gemini-based agents should read `AGENTS.md` first. It is the canonical
repository instruction file for this checkout.

Key reminders:

- Active work centers on `apps/cli/`, `apps/api/`, `apps/console/`,
  `packages/orchestrator/`, `packages/runway-control/`,
  `packages/provider-adapters/`, `packages/lens-store/`,
  `packages/lens-projectors/`, `native/kernel/`, and `skills/`.
- The legacy Python `components/agentlens/` tree has been removed from this
  checkout. Do not recreate it or route active Waygent work there.
- Runtime state such as `.waygent/`, `.agentlens/`, `.claude/`,
  `.codex-orchestrator/`, and `.orchestrator/` must not be committed.
- Waygent run state is written to a platform-aware default root
  (`~/Library/Application Support/waygent/runs/` on macOS,
  `${XDG_DATA_HOME:-$HOME/.local/share}/waygent/runs/` on linux,
  `%LOCALAPPDATA%/waygent/runs/` on win32). See
  `docs/operations/state-root-migration.md`.
- Use the smallest verification command that proves the change, then report
  the exact command and result.
- Historical references to root `docs/superpowers/` may be stale after the
  root docs pruning.
