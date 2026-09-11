# Lens

Lens stores and reads Waygent records. It does not schedule, run
providers, or decide apply.

- `packages/lens-store` — records on disk
- `packages/lens-projectors` — timeline, trust, failure, explain, apply views
- `apps/api`, `apps/console`, `waygent inspect` / `explain` — those views

JSON files last. SQLite is a cache you can rebuild.
`agentlens.event.v3` is the event schema name.

Views rebuild from events, the saved run file, and artifact files. Lens can
report blockers and confidence. `waygent.run_state.v2` still decides resume
and apply.
