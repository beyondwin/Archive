# Lens Architecture

## Role In Waygent

Lens observes and evaluates Waygent evidence. Waygent owns active scheduling,
provider execution, verification, recovery, and apply readiness.

The active Lens implementation is TypeScript-first:

- filesystem evidence helpers live in `packages/lens-store`;
- trust, failure, apply, timeline, and execution explanation projections live
  in `packages/lens-projectors`;
- `apps/api`, `apps/console`, and `waygent inspect/explain` expose those
  projections.

The legacy Python `components/agentlens` tree has been removed from this
checkout. Current Lens work belongs in the TypeScript packages and product
surfaces listed above.

## Durable Artifacts

Filesystem JSON artifacts remain the durable source for run evidence. SQLite
indexes are rebuildable caches when present. `agentlens.event.v3` remains the
durable event schema name, but active readers do not depend on the Python
AgentLens package.

## Projections

Lens projections summarize timelines, trust signals, failures, artifact health,
and apply evidence for API and console surfaces. Projections should be
rebuildable from events, run state, and artifact files.

## Evaluation And Trust

Lens evaluates evidence quality, missing finalization, residual risk, schema
drift, failure patterns, and trust reports. It can report blockers and
confidence, but Waygent runtime state decides whether a run can resume or
apply.

## Boundaries

Lens must not be framed as the active scheduler, provider runner, or apply
readiness owner. It stores and evaluates evidence emitted or owned by Waygent.
