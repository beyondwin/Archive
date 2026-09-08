# Waygent

Run a coding plan with several agents, then apply the result only when it is ready.

Waygent starts tasks, gives each one its own git copy, talks to Codex, Claude, or a fake provider, checks the result, and copies patches back only when the run is ready. Lens keeps the records and the views. You drive it with the `waygent` command.

## Layout

```text
apps/            commands, API, console
packages/        TypeScript scheduler, providers, Lens
native/kernel/   Rust: processes, git copies, apply
docs/            current docs, plus old history
```

## First run

Codex checkout: [local setup](docs/operations/codex-local-setup.md).

```bash
bun install --frozen-lockfile
bun run agent:contract
bun run check
bun run platform:demo
```

```bash
waygent run --latest
waygent status --last
waygent inspect --last --json
waygent explain --last
```

Apply only when your repo is clean and `explain` says the run is ready:

```bash
waygent apply --run <run_id>
```

Live Codex or Claude checks are off by default:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

## Docs

- [Getting started](docs/getting-started.md)
- [Doc index](docs/README.md)
- [How it is built](docs/architecture/waygent.md)
- [How to run it](docs/operations/waygent.md)
- [Events](docs/contracts/events.md) · [run file](docs/contracts/run-state.md) · [provider result](docs/contracts/provider-result.md)

Agent work starts at [AGENTS.md](AGENTS.md). Plans use [PLANS.md](PLANS.md). Reviews use [code_review.md](code_review.md).

Keep `.waygent/`, `.agentlens/`, `.claude/`, `.codex-orchestrator/`, `.orchestrator/`, `.superpowers/`, `node_modules/`, build outputs, and local venvs out of git.
