# GitHub Copilot Instructions - Archive

Read `AGENTS.md` and the nearest subtree `AGENTS.md` before making changes.
They are the canonical project guidance for AI coding agents in this
repository. This file only adds Copilot-specific notes.

Project focus:

- `apps/cli/`, `apps/api/`, and `apps/console/` contain the active Waygent
  product surfaces.
- `packages/lens-store/` and `packages/lens-projectors/` contain the active
  TypeScript Lens storage and projection path.
- `packages/orchestrator/`, `packages/runway-control/`,
  `packages/provider-adapters/`, and `native/kernel/` contain the active
  Waygent runtime.
- `skills/` contains load-bearing local skills used by Codex and Claude.

Follow subtree instructions when present, especially the executor-specific
instructions under `skills/`.

Do not suggest committing runtime state, local caches, secrets, or machine-local
agent files.
