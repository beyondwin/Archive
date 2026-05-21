# Waygent Architecture

Waygent is the user-facing agent platform. The control plane is Bun and
TypeScript; the execution kernel is Rust; AgentLens stores replayable events,
artifacts, and trust projections.

The default execution profile is multi-agent. Scheduler release still comes
from durable safe-wave projection, not from chat context.

The product tree is `apps/`, `packages/`, `native/`, `components/`, `tests/`,
`docs/`, and `skills/waygent/`. AgentLens lives under
`components/agentlens/` as the observability and evaluation component.
