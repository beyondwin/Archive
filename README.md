# Waygent

Waygent is a local agent runtime for running, inspecting, recovering, and
applying multi-agent implementation work. It owns scheduling, worktrees,
provider adapters, verification, recovery, apply readiness, and durable event
emission.

Lens is the TypeScript observability and inspection path inside Waygent.
`agentlens.event.v3` remains the event contract label, but the legacy Python
`components/agentlens/` tree has been removed from the product runtime. KWS
executor skills remain in this repository as local executor contracts, but
they are not the Waygent product runtime.

## Project Map

```text
apps/                  CLI, API, and console surfaces
packages/              TypeScript runtime packages
native/kernel/         Rust execution kernel boundary
skills/                Waygent and KWS executor skill definitions
docs/                  Architecture, operations, contracts, and migration notes
```

## Quick Start

Install dependencies and run the default local checks:

```bash
bun install
bun run check
bun run platform:demo
```

Useful Waygent commands:

```bash
waygent run --latest
waygent status --last
waygent inspect --run <run_id> --json
waygent explain --last
waygent resume --last
waygent apply --run <run_id>
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
- Recovery: [docs/operations/recovery.md](docs/operations/recovery.md)
- Verification: [docs/operations/verification.md](docs/operations/verification.md)
- State root migration: [docs/operations/state-root-migration.md](docs/operations/state-root-migration.md)
- Waygent skill: [skills/waygent/README.md](skills/waygent/README.md)

## Graphify Repository Map

[Graphify](https://github.com/safishamsi/graphify) is an approved development
and documentation-audit tool for this repository. Use it to build a queryable
repo map, find cross-file relationships, and check whether documentation still
matches the current Waygent and Lens structure.

Refresh the local graph after meaningful code or documentation structure
changes:

```bash
graphify update .
```

Query the graph when exploring cross-cutting architecture:

```bash
graphify query "how does Waygent decide apply readiness?"
graphify path "ProviderResult" "Lens"
graphify explain "safe wave"
```

Committed Graphify outputs may include `graphify-out/graph.json`,
`graphify-out/GRAPH_REPORT.md`, and, for smaller graphs,
`graphify-out/graph.html`. Large graphs may skip the HTML view; in that case
use `GRAPH_REPORT.md`, `graph.json`, and `graphify query`. Local-only Graphify
files such as `manifest.json`, `cost.json`, `cache/`, and machine-path metadata
stay ignored. Graphify is not a product runtime dependency and must not replace
the canonical contracts under `docs/`, `packages/`, `native/`, and
`skills/`.

## Working Rules

Read [AGENTS.md](AGENTS.md) before changing this checkout. For complex plans,
use [PLANS.md](PLANS.md). For reviews, use [code_review.md](code_review.md).

Keep runtime state out of git, including `.agentlens/`, `.claude/`,
`.codex-orchestrator/`, `.orchestrator/`, `.superpowers/`, `.waygent/`,
`node_modules/`, build outputs, caches, and local virtualenvs.
