# GitHub Copilot Instructions - Archive

Read `AGENTS.md` before making changes. It is the canonical project guidance
for AI coding agents in this repository.

Project focus:

- `apps/cli/`, `apps/api/`, and `apps/console/` contain the active Waygent
  product surfaces.
- `packages/lens-store/` and `packages/lens-projectors/` contain the active
  TypeScript Lens storage and projection path.
- `packages/orchestrator/`, `packages/runway-control/`,
  `packages/provider-adapters/`, and `native/kernel/` contain the active
  Waygent runtime.
- `skills/` contains load-bearing local skills used by Codex and Claude.

Follow subtree instructions when present, especially
`skills/kws-claude-multi-agent-executor/AGENTS.md`.

Do not suggest committing runtime state, local caches, secrets, or machine-local
agent files.
