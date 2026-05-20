Source-of-truth: the design document wins when this reference and code disagree.

# AgentLens Events

KAO emits `kws.kao.*` events from the runner only. Emission is best-effort and must not block execution.

Payloads use redaction for home paths and secret-like values before writing AgentLens evidence.
