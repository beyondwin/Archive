# Lens

Lens stores and evaluates Waygent evidence. It does not schedule, run
providers, or decide apply.

- `packages/lens-store` — filesystem evidence
- `packages/lens-projectors` — timeline, trust, failure, explain, apply views
- `apps/api`, `apps/console`, `waygent inspect` / `explain` — those views

JSON artifacts are durable. SQLite is a rebuildable cache.
`agentlens.event.v3` is the event schema name.

Projections rebuild from events, run state, and artifact files. Lens can report
blockers and confidence. `waygent.run_state.v2` still decides resume and apply.
