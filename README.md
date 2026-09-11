# Waygent

Local runtime for multi-agent implementation work.

It schedules tasks, isolates worktrees, talks to Codex, Claude, or a fake
provider, verifies the result, and applies only when the run is ready. Lens
stores and projects the evidence. You drive it with the `waygent` CLI.

## First run

See [Getting started](docs/getting-started.md). Codex checkout:
[local setup](docs/operations/codex-local-setup.md).

```bash
bun install --frozen-lockfile
bun run check
bun run platform:demo
```

```bash
waygent run --latest
waygent status --last
waygent explain --last
```

## Docs

- [Getting started](docs/getting-started.md)
- [Doc index](docs/README.md)
- [AGENTS.md](AGENTS.md) for agent work
