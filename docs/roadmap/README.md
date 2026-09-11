# Roadmap

Shipped:

- Waygent as the product runtime
- Bun/TypeScript control plane under `apps/` and `packages/`
- Rust kernel under `native/kernel/`
- `waygent.run_state.v2` plus `platform.*`, `runway.*`, `kernel.*`, `lens.*`
- Fake-provider scenarios, adapters, safe waves, recovery, apply, API, console,
  Lens projections

`docs/superpowers/specs/` and `docs/superpowers/plans/` are the default
`waygent --plan` / `--spec` locations. Older scratch files also live there.

Still in play: execution intelligence, operator UX, keeping Lens projections
aligned with runtime state.

Old migration notes: [migration-history.md](migration-history.md). Current
behavior: [architecture](../architecture/waygent.md),
[operations](../operations/waygent.md), [contracts](../contracts/events.md).
