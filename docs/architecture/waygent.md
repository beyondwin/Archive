# Waygent Architecture

Waygent is the user-facing agent platform. The control plane is Bun and
TypeScript; the execution kernel is Rust; AgentLens stores replayable events,
artifacts, and trust projections.

The default execution profile is multi-agent. Scheduler release still comes
from durable safe-wave projection, not from chat context.

The product tree is `apps/`, `packages/`, `native/`, `tests/`, `docs/`, and
`skills/waygent/`. Existing Python AgentLens and AgentRunway code remains
outside this product tree as reference material until a separate archival
cleanup is approved.
