import type { AgentLensEvent, EventOutcome, TrustImpact } from "@waygent/contracts";
import { nextSequence, readEvents } from "@waygent/lens-store";

export interface RunEventInput {
  run_id: string;
  sequence?: number;
  event_type: string;
  phase: string;
  outcome: EventOutcome;
  summary: string;
  payload: Record<string, unknown>;
  trust_impact?: TrustImpact;
}

export function buildRunEvent(input: RunEventInput): AgentLensEvent {
  const sequence = input.sequence ?? 1;
  return {
    schema: "agentlens.event.v3",
    event_id: `event_${input.run_id}_${sequence}`,
    agentlens_run_id: `lens_${input.run_id}`,
    orchestrator_run_id: input.run_id,
    producer: { name: "waygent", kind: "orchestrator", version: "0.1.0" },
    event_type: input.event_type,
    occurred_at: "2026-05-21T00:00:00Z",
    sequence,
    phase: input.phase,
    outcome: input.outcome,
    severity: input.outcome === "failed" || input.outcome === "blocked" ? "error" : "info",
    trust_impact: input.trust_impact ?? (input.outcome === "success" ? "supports_success" : "neutral"),
    summary: input.summary,
    payload: input.payload
  };
}

export function nextRunEvent(path: string, input: Omit<RunEventInput, "sequence">): AgentLensEvent {
  return buildRunEvent({ ...input, sequence: nextSequence(readEvents(path)) });
}
