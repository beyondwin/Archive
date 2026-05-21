# Waygent Architecture

Waygent is the user-facing agent platform. The control plane is Bun and
TypeScript; the execution kernel is Rust; AgentLens stores replayable events,
artifacts, and trust projections; API and console surfaces expose that evidence
to operators.

The default execution profile is multi-agent. Scheduler release still comes
from durable safe-wave projection, not from chat context.

The product tree is `apps/`, `packages/`, `native/`, `components/`, `tests/`,
`docs/`, and `skills/waygent/`. AgentLens lives under
`components/agentlens/` as the observability and evaluation component.

## Current Architecture Pages

- [Runtime](./runtime.md)
- [AgentLens](./agentlens.md)
- [Decisions](./decisions.md)

The runtime parity target is documented in
[`2026-05-21-waygent-runtime-agentlens-product-parity-design.md`](./2026-05-21-waygent-runtime-agentlens-product-parity-design.md).
The follow-up operational maturity target is documented in
[`2026-05-21-waygent-runtime-v1-operational-maturity-design.md`](./2026-05-21-waygent-runtime-v1-operational-maturity-design.md).
The next source-audited trust-loop slice is documented in
[`2026-05-21-waygent-operational-trust-loop-design.md`](./2026-05-21-waygent-operational-trust-loop-design.md).
Its implementation plan is tracked in
[`../migration/2026-05-21-waygent-operational-trust-loop-implementation-plan.md`](../migration/2026-05-21-waygent-operational-trust-loop-implementation-plan.md).
The follow-up speed and quality target is documented in
[`2026-05-21-waygent-safe-wave-parallel-runtime-design.md`](./2026-05-21-waygent-safe-wave-parallel-runtime-design.md).
Execution intelligence is documented in
[`../superpowers/specs/2026-05-22-waygent-execution-intelligence-design.md`](../superpowers/specs/2026-05-22-waygent-execution-intelligence-design.md).
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

## V1 Operational Maturity

The v1 maturity runtime uses `waygent.run_state.v2` as the authoritative state
for task status, provider attempts, verification evidence, review records,
recovery decisions, drift, completion audit, and apply readiness. AgentLens
events remain append-only replay evidence for API and console inspection.

Operational completion requires these properties:

- Providers run behind role-aware task packets and never write AgentLens events
  directly.
- Provider output can create evidence, but kernel verification and review gates
  decide whether a task has a verified checkpoint.
- Run preflight blocks related dirty source changes and records unrelated dirty
  source warnings before provider dispatch.
- Duplicate run ids cannot erase existing durable run evidence.
- `waygent resume --last` is constrained by v2 recovery policy and must stop on
  ambiguous actions.
- `waygent apply --run <run_id>` is explicit, requires a clean source checkout,
  and blocks unless the v2 readiness projection is `ready`.
- API list/detail, console affordances, `resume`, and `apply` use the same
  readiness projection from completion audit, combined patch evidence,
  checkpoint manifests, and reconciliation drift.
- The offline maturity gate includes `bun run waygent:scenarios`; live Codex
  and Claude checks stay opt-in through `WAYGENT_LIVE_PROVIDER`.
