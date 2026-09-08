# Decisions

| Decision | Position |
| --- | --- |
| Brand | Waygent is the product and the scheduler. |
| Lens | TypeScript in `packages/lens-store` and `packages/lens-projectors`. The Python `components/agentlens` tree was removed. |
| Events | `platform.*`, `runway.*`, `kernel.*`, `lens.*`. |
| Old names | New runs do not emit `agentrunway.*`, `kws-cpe.*`, or `kws-cme.*`. |
| KWS skill events | `kws-cpe.*` / `kws-cme.*` stay skill-local. They are not Waygent product events. |
| Live providers | Codex and Claude smoke checks are off until you turn them on. |

Older move notes can explain the path here. They do not override current
contracts, tests, or runtime docs.
