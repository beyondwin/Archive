# Roadmap

Shipped:

- Waygent as the product runtime
- Bun/TypeScript apps and packages under `apps/` and `packages/`
- Rust kernel under `native/kernel/`
- `waygent.run_state.v2` plus `platform.*`, `runway.*`, `kernel.*`, `lens.*`
- Fake-provider scenarios, adapters, safe task groups, recovery, apply, API,
  console, Lens views

`docs/superpowers/specs/` and `docs/superpowers/plans/` are the default
`waygent --plan` / `--spec` locations. Older scratch files also live there.

Still in play: smarter execution, operator UX, keeping Lens views aligned
with the saved run file.

Old move notes: [migration-history.md](migration-history.md). Current
behavior: [architecture](../architecture/waygent.md),
[operations](../operations/waygent.md), [contracts](../contracts/events.md).
