# KAO Agent Instructions

- Treat `docs/superpowers/specs/2026-05-20-kws-agent-orchestrator-design.md` as the behavioral source of truth.
- Keep the skill thin; put execution logic in `scripts/kao/`.
- Do not let workers write SQLite or AgentLens directly.
- Add or update pytest coverage for every runner behavior change.
- Keep runtime artifacts out of the repo; they belong under `~/.kao/`.
