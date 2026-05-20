Source-of-truth: the design document wins when this reference and code disagree.

# Runtime Adapters

Adapters expose AdapterCapabilities, including runtime, reattach support, streaming support, and `network_egress` allowlists.

Each dispatch returns a WorkerHandle and eventually a validated worker result. Process adapters wrap Claude and Codex CLIs without changing runner state directly.
