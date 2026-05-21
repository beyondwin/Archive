# Waygent Event Contracts

Canonical events use `agentlens.event.v3`. Product event families are:

- `platform.*`
- `runway.*`
- `kernel.*`
- `lens.*`

Legacy KWS executor namespaces are rejected by the contract validator.
Filesystem JSONL artifacts remain the source of truth. SQLite is a rebuildable
projection cache.
