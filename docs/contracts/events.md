# Waygent Event Contracts

Related contracts:

- [Run state](./run-state.md)
- [Provider result](./provider-result.md)

Canonical events use `agentlens.event.v3`. The schema name is retained for
durable compatibility and does not require the legacy Python AgentLens runtime.
Product event families are:

- `platform.*`
- `runway.*`
- `kernel.*`
- `lens.*`

Legacy KWS executor namespaces are rejected by the contract validator.
Filesystem JSONL artifacts remain the source of truth. SQLite is a rebuildable
projection cache.

Waygent owns active runtime events. Lens reads those events through
`packages/lens-store` and `packages/lens-projectors`. KWS executor namespaces
are historical and must not be emitted by new Waygent runs. Python AgentLens
schemas and projections are not part of the active event contract.
