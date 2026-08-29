# Waygent

Local runtime for multi-agent implementation work.

It schedules tasks, isolates worktrees, talks to Codex, Claude, or a fake provider, verifies the result, and applies only when the run is ready. Lens stores and projects the evidence. You drive it with the `waygent` CLI, not a skill.

## Layout

```text
apps/            CLI, API, console
packages/        TypeScript control plane
native/kernel/   Rust execution kernel
skills/_legacy/  Frozen executor trees
docs/            Current docs, plus history
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

Apply only when the source checkout is clean and `explain` says the run is ready:

```bash
waygent apply --run <run_id>
```

Live provider checks are opt-in:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

## Docs

- [Getting started](docs/getting-started.md)
- [Doc index](docs/README.md)
- [Architecture](docs/architecture/waygent.md)
- [Operations](docs/operations/waygent.md)
- [Events](docs/contracts/events.md) · [run state](docs/contracts/run-state.md) · [provider result](docs/contracts/provider-result.md)

Agent work starts at [AGENTS.md](AGENTS.md). Plans use [PLANS.md](PLANS.md). Reviews use [code_review.md](code_review.md).

Keep `.waygent/`, `.agentlens/`, `.claude/`, `.codex-orchestrator/`, `.orchestrator/`, `.superpowers/`, `node_modules/`, build outputs, and local venvs out of git.
