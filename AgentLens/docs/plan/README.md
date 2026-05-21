# AgentLens Plan Directory

This directory contains historical plans and current planning artifacts. Do not
assume the v0 task file is the active plan for new work.

| File | Status | Role |
|------|--------|------|
| [`2026-05-21-full-rust-agent-platform-phase-1-skeleton-contracts.md`](2026-05-21-full-rust-agent-platform-phase-1-skeleton-contracts.md) | Blocked | Rust skeleton plan. It must be revised after contract reconciliation before execution. |
| [`2026-05-19-agentlens-v1-and-kws-unification.md`](2026-05-19-agentlens-v1-and-kws-unification.md) | Historical context | Older AgentLens/KWS migration plan. Do not treat `kws-cpe` / `kws-cme` as the new architecture. |
| [`agentlens_v0_tasks.md`](agentlens_v0_tasks.md) | Historical v0 | Machine-friendly v0 task breakdown retained for reference. |
| [`archive/agentlens_v0_detailed_plan.md`](archive/agentlens_v0_detailed_plan.md) | Archived | Original PM/lead-engineer-facing milestone narrative. |

Current design authority:

- Full Rust target:
  [`../spec/2026-05-21-full-rust-agent-platform-rewrite-design.md`](../spec/2026-05-21-full-rust-agent-platform-rewrite-design.md)
- Required pre-implementation reconciliation:
  [`../spec/2026-05-21-contract-first-unified-agent-platform-design.md`](../spec/2026-05-21-contract-first-unified-agent-platform-design.md)

Next planning work should create a new contract reconciliation implementation
plan before any Rust workspace skeleton is executed.
