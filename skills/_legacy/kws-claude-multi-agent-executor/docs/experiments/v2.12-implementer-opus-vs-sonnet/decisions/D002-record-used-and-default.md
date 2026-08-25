# D002 — Record both used model and default in state.json

**Status**: Accepted
**Date**: 2026-05-16

## Context

When `implementer_model=opus` overrides the default, a stale reader of `state.json` (a week later, a different machine, a comparison script) needs to know not just what model ran but what the *default* at the time of the run would have been. Otherwise: silent drift if the skill default changes between runs, and the comparison is no longer reproducible.

User specifically requested this when designing the experiment.

## Decision

`state.json` Phase 0 Step 7 records:

```json
"implementer_model": {
  "used": "opus" | "sonnet",
  "default": "sonnet"
}
```

The `default` field tracks what the skill would have dispatched if no override were passed. If the production default changes in a later skill version, that change is visible in the field — old runs still show their actual contemporaneous default.

The Implementer prompt's learning-log emit template (`references/implementer-prompt.md`) also receives a `{implementer_model}` placeholder that fills `subagent.model`. This keeps learning-log events accurate for both arms.

## Consequences

- Aggregation scripts group on `implementer_model.used` and can detect drift via `implementer_model.default`.
- Schema change to `state.json` — additive field, no migration required.
- Old runs (v2.10.2 and earlier) won't have this field; aggregator must handle absence by treating it as `{"used": "sonnet", "default": "sonnet"}` (the historical fact for those runs).

## Alternatives considered

- **Only record `used`.** Rejected — loses the reproducibility context that motivated the experiment.
- **Record full args dict.** Overkill for current need; can be added later if more overrides accumulate.
