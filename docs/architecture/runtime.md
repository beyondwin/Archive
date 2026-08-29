# Runtime

Waygent owns scheduling, state, worktrees, providers, verification, recovery,
apply, and event emission. CLI, API, and console are windows onto that state.

## Control plane

`apps/` and `packages/` are Bun/TypeScript. `apps/cli` is the operator surface.
`packages/orchestrator` creates runs, dispatches safe-wave tasks, records
completion audit, and decides apply readiness.

## Kernel

`native/kernel/` handles process supervision, worktrees, artifact sealing,
policy, and diff application. Run the Rust workspace tests when kernel code
changes.

## Safe waves

A task joins a wave only when file claims, dependencies, risk, and checkpoints
allow it. Chat cannot override that.

## Providers

`packages/provider-adapters` keeps fake, Codex, and Claude behind one
`WorkerResult` boundary. Codex and Claude run configured process commands, take
the task prompt on stdin, and normalize JSON, JSONL, or fenced JSON into
`runway.worker_result.v1`.

## Verify, recover, apply

Provider output is evidence, not a pass. Kernel verification, review gates,
checkpoint manifests, and completion audit decide whether work is usable.

`waygent apply --run <run_id>` is the only source-checkout mutation. It needs
`waygent.run_state.v2` ready, checkpoint manifests, combined patch evidence,
dry-run results, and a clean source checkout.

## Default gates

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
```
