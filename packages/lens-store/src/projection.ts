import type { AgentLensEvent } from "@waygent/contracts";

export interface RunSummary {
  run_id: string;
  total_events: number;
  last_event_type: string | null;
  failed_events: number;
  artifact_count: number;
}

export function rebuildRunSummary(events: AgentLensEvent[]): RunSummary {
  const runId = events[0]?.orchestrator_run_id ?? "run_empty";
  return {
    run_id: runId,
    total_events: events.length,
    last_event_type: events.at(-1)?.event_type ?? null,
    failed_events: events.filter((event) => event.outcome === "failed" || event.outcome === "blocked").length,
    artifact_count: events.flatMap((event) => event.artifacts ?? []).length
  };
}
