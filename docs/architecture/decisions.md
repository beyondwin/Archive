# Waygent Architecture Decisions

| Decision | Current Position |
| --- | --- |
| Product brand | Waygent is the user-facing platform and orchestrator. |
| Observability | AgentLens is the observability and evaluation component. |
| Event families | Active events use `platform.*`, `runway.*`, `kernel.*`, and `lens.*`. |
| Legacy namespaces | New Waygent runs must not emit `agentrunway.*`, `kws-cpe.*`, or `kws-cme.*`. |
| Graphify | Graphify is an approved development and documentation-audit tool, not a runtime dependency. |
| Live providers | Codex and Claude live smoke checks are opt-in. |

These decisions are current product guidance. Older migration records can
explain how the repository arrived here, but they do not override current
contracts, tests, and runtime docs.
