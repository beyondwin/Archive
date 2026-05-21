# Waygent Roadmap

## Current Product Baseline

Waygent is the active product runtime and AgentLens is the observability and
evaluation component. Current behavior is documented by the root README,
architecture docs, operations docs, contract docs, package code, native kernel
code, tests, and skill docs.

## Shipped Work

- Waygent brand and active runtime boundary.
- Bun and TypeScript control plane under `apps/` and `packages/`.
- Rust kernel boundary under `native/kernel/`.
- `waygent.run_state.v2` runtime state and active `platform.*`, `runway.*`,
  `kernel.*`, and `lens.*` event families.
- Fake-provider scenarios, provider adapters, safe-wave scheduling, recovery,
  apply-readiness checks, API, console, and AgentLens projection surfaces.

## Design-Only Work

Recent docs under `docs/superpowers/specs/` and `docs/superpowers/plans/`
capture next-step designs. Treat them as implementation proposals until their
contracts, code, and verification have shipped.

## Future Work

- Continue improving execution intelligence, reliability, and operator UX.
- Keep Lens and runtime projections aligned.
- Reduce stale legacy language in current-facing docs.
- Refresh Graphify maps after meaningful structure changes.

## Historical Migration Records

Use [migration-history.md](migration-history.md) for the full list of preserved
`docs/migration/` records. These files explain prior decisions and migration
steps, but current architecture, operations, and contracts are the product entry
points.
