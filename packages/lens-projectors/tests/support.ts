import type { AgentLensEvent } from "@waygent/contracts";

export function demoEvent(overrides: Partial<AgentLensEvent> = {}): AgentLensEvent {
  return {
    schema: "agentlens.event.v3",
    event_id: `event_demo_${overrides.sequence ?? 1}`,
    agentlens_run_id: "run_lens",
    orchestrator_run_id: "run_demo",
    producer: { name: "waygent", kind: "orchestrator", version: "0.1.0" },
    event_type: "runway.verification_result",
    occurred_at: "2026-05-21T00:00:00Z",
    sequence: 1,
    phase: "verify",
    outcome: "success",
    severity: "info",
    trust_impact: "supports_success",
    summary: "Verification passed.",
    payload: { task_id: "task_demo" },
    ...overrides
  };
}
