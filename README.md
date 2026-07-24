# Waygent

Waygent is a local agent runtime for running, inspecting, recovering, and
applying multi-agent implementation work. It owns scheduling, worktrees,
provider adapters, verification, recovery, apply readiness, and durable event
emission.

Lens is the TypeScript observability and inspection path inside Waygent.
`agentlens.event.v3` remains the event contract label, but the legacy Python
`components/agentlens/` tree has been removed from the product runtime. KWS
plan-runner and executor skills remain in this repository as local execution
contracts, but they are not the Waygent product runtime.

## Project Map

```text
apps/                  CLI, API, and console surfaces
packages/              TypeScript runtime packages
native/kernel/         Rust execution kernel boundary
skills/                Waygent and KWS runner/executor skill definitions
docs/                  Architecture, operations, contracts, and migration notes
```

## Quick Start

For a first Codex checkout, complete the
[local operator setup](docs/operations/codex-local-setup.md). Install locked
dependencies and run the repository agent contract before the default product
checks:

```bash
bun install --frozen-lockfile
bun run agent:contract
bun run check
bun run platform:demo
```

Useful Waygent commands:

```bash
waygent run --latest
waygent run-chain --plan <p1.md> --plan <p2.md>
waygent status --last
waygent events --last
waygent inspect --run <run_id> --json
waygent explain --last
waygent resume --last
waygent verify --run <run_id> --last
waygent apply --run <run_id>
waygent repair --run <run_id> [--task <task_id>] [--instruction "<note>"]
waygent decisions --last
waygent cost --last
waygent watch --last [--json] [--filter all|task_transition|failure|cost]
waygent orphans [--stale] [--cleanup-worktree <run_id>]
waygent lint-design --path <design.md>
waygent lint-plan --path <waygent-task.md>
waygent scaffold-plan --id <task_id> --title <title> --claim <path:mode> --risk <low|medium|high> --verify <command>
```

Live Codex and Claude provider checks are opt-in because they require installed
and authenticated local CLIs:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

## Architecture

Waygent uses a Bun/TypeScript control plane, a Rust execution kernel, and
filesystem event journals as replayable evidence. Runtime decisions come from
durable state and TypeScript projections, not from chat context.

- Runtime overview: [docs/architecture/waygent.md](docs/architecture/waygent.md)
- Documentation index: [docs/README.md](docs/README.md)
- Getting started: [docs/getting-started.md](docs/getting-started.md)
- Event contracts: [docs/contracts/events.md](docs/contracts/events.md)
- Run-state contract: [docs/contracts/run-state.md](docs/contracts/run-state.md)
- Provider-result contract: [docs/contracts/provider-result.md](docs/contracts/provider-result.md)
- Operations: [docs/operations/waygent.md](docs/operations/waygent.md)
- Codex local setup: [docs/operations/codex-local-setup.md](docs/operations/codex-local-setup.md)
- Recovery: [docs/operations/recovery.md](docs/operations/recovery.md)
- Verification: [docs/operations/verification.md](docs/operations/verification.md)
- State root migration: [docs/operations/state-root-migration.md](docs/operations/state-root-migration.md)
- Skill overview and installation: [skills/README.md](skills/README.md)
- Waygent skill: [skills/waygent/README.md](skills/waygent/README.md)

## Working Rules

Read [AGENTS.md](AGENTS.md) before changing this checkout. For complex plans,
use [PLANS.md](PLANS.md). For reviews, use [code_review.md](code_review.md).

Keep runtime state out of git, including `.agentlens/`, `.claude/`,
`.codex-orchestrator/`, `.orchestrator/`, `.superpowers/`, `.waygent/`,
`node_modules/`, build outputs, caches, and local virtualenvs.
