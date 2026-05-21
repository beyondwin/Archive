import type { AgentLensEvent, FailureClass, LensRunwayProjection, RunStatus } from "@waygent/contracts";

export type TrustStatus = "trusted" | "failed" | "insufficient_evidence";

export interface TrustReport {
  trust_status: TrustStatus;
  total_events: number;
  evidence_score: number;
  reasons: string[];
}

export interface FailureSummary {
  task_id: string;
  failure_class: FailureClass | "unknown";
  recovery_action: string;
  count: number;
}

export interface TimelineEntry {
  sequence: number;
  event_type: string;
  phase: string;
  outcome: string;
  summary: string;
}

export function projectTrustReport(events: AgentLensEvent[]): TrustReport {
  const verification = events.filter((event) => event.event_type.includes("verification") && event.outcome === "success");
  const kernel = events.filter((event) => event.event_type.startsWith("kernel.") && event.outcome === "success");
  const failures = events.filter((event) => event.outcome === "failed" || event.outcome === "blocked");
  if (failures.length > 0) {
    return { trust_status: "failed", total_events: events.length, evidence_score: -failures.length, reasons: ["failure evidence present"] };
  }
  if (verification.length === 0 && kernel.length === 0) {
    return { trust_status: "insufficient_evidence", total_events: events.length, evidence_score: 0, reasons: ["verification or kernel evidence required"] };
  }
  return {
    trust_status: "trusted",
    total_events: events.length,
    evidence_score: verification.length * 2 + kernel.length,
    reasons: ["verification/kernel evidence outranks final agent claims"]
  };
}

export function projectRunwayProjection(events: AgentLensEvent[], safe_wave: string[] = []): LensRunwayProjection {
  const trust = projectTrustReport(events);
  const blocked = events.some((event) => event.outcome === "blocked");
  const failed = events.some((event) => event.outcome === "failed");
  const legacy = events.some((event) => event.event_type.startsWith("agentrunway."));
  const status: RunStatus = blocked
    ? "blocked"
    : failed
      ? "failed"
      : trust.trust_status === "trusted"
        ? "completed"
        : "running";

  return {
    schema: "lens.runway_projection.v1",
    run_id: events[0]?.orchestrator_run_id ?? "run_empty",
    status,
    safe_wave,
    trust_status: trust.trust_status,
    event_count: events.length,
    legacy_source: legacy ? "agentrunway" : null
  };
}

export function projectFailureSummary(events: AgentLensEvent[]): FailureSummary[] {
  const grouped = new Map<string, FailureSummary>();
  for (const event of events) {
    if (event.outcome !== "failed" && event.outcome !== "blocked") continue;
    const taskId = String(event.payload.task_id ?? "task_unknown");
    const failureClass = (event.payload.failure_class ?? "unknown") as FailureSummary["failure_class"];
    const key = `${taskId}:${failureClass}`;
    const existing = grouped.get(key);
    grouped.set(key, {
      task_id: taskId,
      failure_class: failureClass,
      recovery_action: failureClass === "verification_failed" ? "retry_with_evidence" : "request_decision",
      count: (existing?.count ?? 0) + 1
    });
  }
  return [...grouped.values()];
}

export function projectTimeline(events: AgentLensEvent[]): TimelineEntry[] {
  return [...events]
    .sort((a, b) => a.sequence - b.sequence)
    .map((event) => ({
      sequence: event.sequence,
      event_type: event.event_type,
      phase: event.phase,
      outcome: event.outcome,
      summary: event.summary
    }));
}
