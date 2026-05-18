# AgentLens v0 — Plan Directory

| File | Role | Audience |
|------|------|----------|
| [`agentlens_v0_tasks.md`](agentlens_v0_tasks.md) | Machine-friendly 25-task breakdown in `### Task N:` format. **This is the canonical plan consumed by `kws-claude-multi-agent-executor`.** | Automation, executors |
| [`archive/agentlens_v0_detailed_plan.md`](archive/agentlens_v0_detailed_plan.md) | Original PM/lead-engineer-facing milestone narrative (M0–M8). Archived after v0 ship because its `### 3.1 M0 ...` headers fail the executor plan gate. Retained for design context. | Humans reading rationale |

Module-level specification lives in [`../spec/agentlens_v0_implementation_spec.md`](../spec/agentlens_v0_implementation_spec.md); architectural ADRs live under [`../adr/`](../adr/).

For v1 work, copy `agentlens_v0_tasks.md` to `agentlens_v1_tasks.md` and keep this directory's structure (one machine plan + archived narratives).
