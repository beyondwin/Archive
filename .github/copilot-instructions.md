# GitHub Copilot Instructions - Archive

Read `AGENTS.md` before making changes. It is the canonical project guidance
for AI coding agents in this repository.

Project focus:

- `AgentLens/` contains the Python package, CLI, tests, and React dashboard.
- `skills/` contains load-bearing executor skills used by Codex and Claude.

Follow subtree instructions when present, especially
`skills/agent-runway/AGENTS.md` and
`skills/kws-claude-multi-agent-executor/AGENTS.md`.

Do not suggest committing runtime state, local caches, secrets, or machine-local
agent files.
