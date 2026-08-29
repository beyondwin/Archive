# Decisions

| Decision | Position |
| --- | --- |
| Brand | Waygent is the product and orchestrator. |
| Lens | TypeScript in `packages/lens-store` and `packages/lens-projectors`. The Python `components/agentlens` tree was removed. |
| Events | `platform.*`, `runway.*`, `kernel.*`, `lens.*`. |
| Legacy namespaces | New runs do not emit `agentrunway.*`, `kws-cpe.*`, or `kws-cme.*`. |
| KWS skill telemetry | `kws-cpe.*` / `kws-cme.*` stay skill-local. They are not Waygent product telemetry. |
| Live providers | Codex and Claude smoke checks are opt-in. |

Older migration notes can explain the path here. They do not override current
contracts, tests, or runtime docs.
