# Waygent Architecture

Waygent is the user-facing agent platform. The control plane is Bun and
TypeScript; the execution kernel is Rust; AgentLens stores replayable events,
artifacts, and trust projections.

The default execution profile is multi-agent. Scheduler release still comes
from durable safe-wave projection, not from chat context.

The product tree is `apps/`, `packages/`, `native/`, `components/`, `tests/`,
`docs/`, and `skills/waygent/`. AgentLens lives under
`components/agentlens/` as the observability and evaluation component.

The runtime parity target is documented in
[`2026-05-21-waygent-runtime-agentlens-product-parity-design.md`](./2026-05-21-waygent-runtime-agentlens-product-parity-design.md).
Waygent owns the product runtime directly; KWS executor skills are not product
dependencies.

## Runtime Parity Surface

Waygent now owns the local product execution path end to end:

- `skills/waygent` maps operator intent to the `waygent` CLI and stays thin.
- `apps/cli` resolves plan files, starts durable runs, and reads persisted
  status, events, inspection, explanation, resume, and apply state.
- `packages/orchestrator` creates durable state, records completion audits,
  plans isolated Waygent-owned worktrees, and dispatches every safe-wave task.
- `packages/provider-adapters` keeps fake, Codex, and Claude behind the same
  `WorkerResult` boundary without direct AgentLens writes. Codex and Claude
  execute configured process commands, pass the task prompt through stdin, and
  normalize direct JSON, JSONL result envelopes, and fenced JSON responses into
  `runway.worker_result.v1`.
- `packages/lens-store` and `packages/lens-projectors` rebuild timeline, trust,
  failure, and apply views from filesystem JSONL events.
- `apps/api` and `apps/console` can inspect a run created by `waygent run`, not
  only static demo fixtures.

The active event families remain `platform.*`, `runway.*`, `kernel.*`, and
`lens.*`.
