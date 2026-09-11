# Waygent

Run a coding plan with several agents, then apply the result only when it is ready.

Waygent starts tasks, gives each one its own git copy, talks to Codex, Claude, or a fake
provider, checks the result, and copies patches back only when the run is ready. Lens
keeps the records and the views. You drive it with the `waygent` command.

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
