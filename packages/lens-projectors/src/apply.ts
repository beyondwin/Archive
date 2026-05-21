import type { AgentLensEvent } from "@waygent/contracts";

export interface ApplyProjection {
  status: "not_ready" | "ready" | "blocked" | "applied";
  reason: string | null;
}

export function projectApplyState(events: AgentLensEvent[]): ApplyProjection {
  if (events.some((event) => event.event_type === "runway.apply_completed")) {
    return { status: "applied", reason: null };
  }

  const blocked = [...events].reverse().find((event) => event.event_type === "runway.apply_blocked");
  if (blocked) {
    return { status: "blocked", reason: String(blocked.payload.reason ?? "unknown") };
  }

  if (events.some((event) => event.event_type === "runway.verification_result" && event.outcome === "success")) {
    return { status: "ready", reason: null };
  }

  return { status: "not_ready", reason: "missing_successful_verification" };
}
