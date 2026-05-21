# Waygent Architecture Decisions

| Decision | Current Position |
| --- | --- |
| Product brand | Waygent is the user-facing platform and orchestrator. |
| Observability | Lens is the TypeScript storage and projection path in `packages/lens-store` and `packages/lens-projectors`; Python AgentLens is legacy pending deletion. |
| Event families | Active events use `platform.*`, `runway.*`, `kernel.*`, and `lens.*`. |
| Legacy namespaces | New Waygent runs must not emit `agentrunway.*`, `kws-cpe.*`, or `kws-cme.*`. |
| KWS executor telemetry | `kws-cpe.*` and `kws-cme.*` remain skill-local/external observability for KWS executor skills only. They are not active Waygent product telemetry and may degrade if no external `agentlens` CLI is installed after the legacy Python tree is deleted. |
| Graphify | Graphify is an approved development and documentation-audit tool, not a runtime dependency. |
| Live providers | Codex and Claude live smoke checks are opt-in. |

These decisions are current product guidance. Older migration records can
explain how the repository arrived here, but they do not override current
contracts, tests, and runtime docs.

KWS executor skill references to `agentlens run-open`,
`agentlens event append`, `agentlens run-close`, `agentlens events`,
`AGENTLENS_*`, `agentlens_orchestration_run`, `kws-cpe.*`, and `kws-cme.*` are
intentionally preserved as local skill telemetry. They do not block deletion of
the legacy Python `components/agentlens` product tree because the skills guard
AgentLens calls as best-effort observability and keep executor state outside
AgentLens as the authoritative resume source.
