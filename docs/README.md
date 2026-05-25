# Waygent Documentation

## Start Here

Waygent is the active local agent runtime. Start with the root
[`README.md`](../README.md) for the product overview, then use this index to
choose the current architecture, operation, contract, component, or skill docs
that match your role.

Current docs describe the Waygent product runtime. Migration plans and older
design records remain available as history, but they are not the first path for
understanding current behavior.

## Reader Paths

- Reviewers: read the root `README.md`, then `architecture/waygent.md`, then
  `operations/waygent.md`.
- Operators: read `getting-started.md`, `operations/waygent.md`,
  `operations/recovery.md`, and `operations/verification.md`.
- Developers: read `architecture/waygent.md`, `contracts/events.md`,
  `contracts/run-state.md`, and `contracts/provider-result.md`.
- AI agents: read `../AGENTS.md`, the nearest subtree `AGENTS.md`,
  `../PLANS.md`, `../code_review.md`, and the target skill README.

## Current Product Docs

- [Architecture overview](architecture/waygent.md)
- [Runtime architecture](architecture/runtime.md)
- [AgentLens architecture](architecture/agentlens.md)
- [Architecture decisions](architecture/decisions.md)
- [Operations](operations/waygent.md)
- [Recovery](operations/recovery.md)
- [Verification](operations/verification.md)
- [Plan authoring](operations/plan-authoring.md)
- [State root migration](operations/state-root-migration.md)
- [Event contract](contracts/events.md)
- [Run-state contract](contracts/run-state.md)
- [Provider-result contract](contracts/provider-result.md)
- [Roadmap](roadmap/README.md)
- [Migration history](roadmap/migration-history.md)

Migration documents are historical planning records. Use the roadmap index for
status and use architecture, operations, and contracts for current runtime
behavior.

## Lens Docs

- [Lens architecture](architecture/agentlens.md)
- [Event contract](contracts/events.md)
- [Run-state contract](contracts/run-state.md)
- [Operations](operations/waygent.md)

Lens records, queries, evaluates, and visualizes run evidence through the
TypeScript Waygent path. Waygent owns active scheduling, provider execution,
verification, recovery, and apply readiness.

## Skill Docs

- [Skills overview](../skills/README.md)
- [Waygent skill](../skills/waygent/README.md)
- [Codex executor skill](../skills/kws-codex-plan-executor/README.md)
- [Claude executor skill](../skills/kws-claude-multi-agent-executor/README.md)

The Waygent skill routes natural-language operator intent to the CLI. The KWS
executor skills remain load-bearing local executor contracts, but they are not
the Waygent product runtime.

## Historical Planning

- [Roadmap](roadmap/README.md)
- [Migration history](roadmap/migration-history.md)
- [Migration records](migration/)
- [Superpowers plans](superpowers/plans/)
- [Superpowers specs](superpowers/specs/)

Historical records preserve why the repository moved into the current Waygent
shape. Do not treat older AgentRunway, KWS CPE, or KWS CME routing language as
active product architecture unless a current doc explicitly says so.

## Graphify Map

Graphify is approved as a repository map and documentation-audit tool. When
`graphify-out/` exists, use it as navigation and audit evidence, then refresh it
after meaningful code or documentation structure changes:

```bash
graphify update .
graphify query "how does Waygent decide apply readiness?" --graph graphify-out/graph.json
```

Graphify output is not runtime state and does not replace contracts, package
code, native kernel code, tests, or AgentLens artifacts.
