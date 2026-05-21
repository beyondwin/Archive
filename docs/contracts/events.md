# Waygent Event Contracts

Related contracts:

- [Run state](./run-state.md)
- [Provider result](./provider-result.md)

Canonical events use `agentlens.event.v3`. Product event families are:

- `platform.*`
- `runway.*`
- `kernel.*`
- `lens.*`

Legacy KWS executor namespaces are rejected by the contract validator.
Filesystem JSONL artifacts remain the source of truth. SQLite is a rebuildable
projection cache.

Waygent owns active runtime events. KWS executor namespaces are historical and
must not be emitted by new Waygent runs. AgentLens reads Waygent events and may
retain legacy AgentRunway read compatibility for old artifacts.
