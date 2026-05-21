# AgentLens Plan Directory

This directory contains historical plans and current planning artifacts. Do not
assume the v0 task file is the active plan for new work.

| File | Status | Role |
|------|--------|------|
| [`2026-05-21-waygent-full-platform-implementation-program.md`](2026-05-21-waygent-full-platform-implementation-program.md) | Current full implementation program | End-to-end implementation coverage for the complete Waygent spec. |
| [`2026-05-21-bun-control-plane-rust-kernel-platform-phase-1-spine.md`](2026-05-21-bun-control-plane-rust-kernel-platform-phase-1-spine.md) | Current Phase 1 executable plan | First Waygent Bun control plane + Rust execution kernel platform spine. |
| [`2026-05-21-contract-first-unified-agent-platform.md`](2026-05-21-contract-first-unified-agent-platform.md) | Superseded planning context | Waygent contract reconciliation plan for the previous Full Rust path. |
| [`2026-05-21-full-rust-agent-platform-phase-1-skeleton-contracts.md`](2026-05-21-full-rust-agent-platform-phase-1-skeleton-contracts.md) | Blocked | Rust skeleton plan. It must be revised after contract reconciliation before execution. |
| [`2026-05-19-agentlens-v1-and-kws-unification.md`](2026-05-19-agentlens-v1-and-kws-unification.md) | Historical context | Older AgentLens/KWS migration plan. Do not treat `kws-cpe` / `kws-cme` as the new architecture. |
| [`agentlens_v0_tasks.md`](agentlens_v0_tasks.md) | Historical v0 | Machine-friendly v0 task breakdown retained for reference. |
| [`archive/agentlens_v0_detailed_plan.md`](archive/agentlens_v0_detailed_plan.md) | Archived | Original PM/lead-engineer-facing milestone narrative. |

Current design authority:

- Waygent Bun control plane + Rust execution kernel target:
  [`../spec/2026-05-21-bun-control-plane-rust-kernel-agent-platform-design.md`](../spec/2026-05-21-bun-control-plane-rust-kernel-agent-platform-design.md)
- Full Rust target:
  [`../spec/2026-05-21-full-rust-agent-platform-rewrite-design.md`](../spec/2026-05-21-full-rust-agent-platform-rewrite-design.md)
- Required pre-implementation reconciliation:
  [`../spec/2026-05-21-contract-first-unified-agent-platform-design.md`](../spec/2026-05-21-contract-first-unified-agent-platform-design.md)

Execution work should follow the Waygent Bun control plane + Rust kernel
full implementation program. The Phase 1 spine plan is the first executable
slice, not the complete product plan. Do not return to the previous Full Rust
path unless the user explicitly asks for it.
