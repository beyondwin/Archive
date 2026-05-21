# AgentRunway Agent Instructions

- Treat `SKILL.md`, `README.md`, and `references/` as the current behavioral
  source of truth. Historical root `docs/superpowers/...` files may no longer
  exist in this pruned Archive checkout.
- Keep the skill thin; put execution logic in `scripts/agentrunway/`.
- Do not let workers write SQLite or AgentLens directly.
- Add or update pytest coverage for every runner behavior change.
- Keep runtime artifacts out of the repo; they belong under `~/.agentrunway/`.
