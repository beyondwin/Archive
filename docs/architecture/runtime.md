# Waygent Runtime Architecture

## Runtime Boundary

Waygent owns scheduling, state, worktrees, provider adapters, verification,
recovery, apply, and AgentLens event emission. Operators interact with the CLI,
API, and console, but runtime decisions come from durable state and projections.

Active event families are `platform.*`, `runway.*`, `kernel.*`, and `lens.*`.

## Control Plane

The Bun and TypeScript control plane lives under `apps/` and `packages/`.
`apps/cli` exposes run, status, inspect, explain, resume, and apply commands.
`packages/orchestrator` creates durable runs, dispatches tasks, records
completion audit evidence, coordinates recovery, and checks apply readiness.

## Execution Kernel

The Rust kernel under `native/kernel/` owns lower-level execution boundaries
such as process supervision, worktree operations, artifact sealing, policy, and
diff application. Kernel checks are part of the stronger local verification
gate when runtime code changes.

## Scheduling And Safe Waves

Waygent releases work through scheduler-approved safe waves. A task can run in
parallel only when file claims, dependencies, risk, and checkpoint requirements
allow it. Chat context does not override safe-wave barriers.

## Provider Adapters

`packages/provider-adapters` keeps fake, Codex, and Claude behind the same
provider boundary. Providers return normalized worker results; they do not write
AgentLens events directly. Waygent records provider attempts, stdout, stderr,
worker-result artifacts, and accepted runtime evidence.

## Verification And Recovery

Verification is runtime-owned. Provider output can create evidence, but kernel
verification, review gates, checkpoint manifests, artifact reconciliation, and
completion audit decide whether task work is usable. Recovery policy handles
dirty source checkouts, missing artifacts, state drift, provider failures, and
verification failures before resume or apply.

## Apply Readiness

Apply readiness is derived from `waygent.run_state.v2`, checkpoint manifests,
combined patch evidence, dry-run results, completion audit, reconciliation, and
source checkout cleanliness. `waygent apply --run <run_id>` is the only source
checkout mutation path.

## Default Gates

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
```
