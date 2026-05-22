import type {
  AgentLensEvent,
  ApplyReadinessProjection,
  RunStatus,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectApplyReadinessFromState, projectApplyState } from "./apply";
import { projectExecutionExplanationFromState } from "./executionExplanation";
import { projectOperationalMaturityFromState } from "./operationalMaturity";
import { projectFailureSummary, projectTimeline, projectTrustReport } from "./trust";

export type RunReadModelStateBlocker =
  | { status: "missing"; reason: "missing_run_state_v2" }
  | { status: "unsupported"; reason: "unsupported_run_state"; schema?: unknown }
  | { status: "invalid"; reason: "invalid_run_state_v2"; error?: string };

export interface RunReadModelInput {
  run_id: string;
  events: AgentLensEvent[];
  state?: WaygentRunStateV2 | null;
  state_error?: RunReadModelStateBlocker | null;
}

export interface RunReadModelProjection {
  run_id: string;
  status: RunStatus;
  trust_status: ReturnType<typeof projectTrustReport>["trust_status"];
  apply_status: ApplyReadinessProjection["status"];
  total_events: number;
  last_event_type: string | null;
  safe_wave: string[];
  failures: ReturnType<typeof projectFailureSummary>;
  timeline: ReturnType<typeof projectTimeline>;
  trust: ReturnType<typeof projectTrustReport>;
  event_apply_state: ReturnType<typeof projectApplyState>;
  apply_readiness: ApplyReadinessProjection | null;
  execution_explanation: ReturnType<typeof projectExecutionExplanationFromState> | null;
  operational_maturity: ReturnType<typeof projectOperationalMaturityFromState> | null;
  state: WaygentRunStateV2 | null;
  state_blocker: RunReadModelStateBlocker | null;
}

export function projectRunReadModel(input: RunReadModelInput): RunReadModelProjection {
  const trust = projectTrustReport(input.events);
  const failures = projectFailureSummary(input.events);
  const timeline = projectTimeline(input.events);
  const eventApplyState = projectApplyState(input.events);
  const lastEventType = input.events.at(-1)?.event_type ?? null;

  if (input.state) {
    const executionExplanation = projectExecutionExplanationFromState(input.state);
    const operationalMaturity = projectOperationalMaturityFromState({ state: input.state, events: input.events });
    const applyReadiness = operationalMaturity.apply_readiness;
    return {
      run_id: input.run_id,
      status: runStatusFromV2(input.state.status),
      trust_status: trust.trust_status,
      apply_status: applyReadiness.status,
      total_events: input.events.length,
      last_event_type: lastEventType,
      safe_wave: executionExplanation.waves[0]?.ready ?? [],
      failures,
      timeline,
      trust,
      event_apply_state: eventApplyState,
      apply_readiness: applyReadiness,
      execution_explanation: executionExplanation,
      operational_maturity: operationalMaturity,
      state: input.state,
      state_blocker: null
    };
  }

  return {
    run_id: input.run_id,
    status: statusFromEvents(input.events, trust.trust_status),
    trust_status: trust.trust_status,
    apply_status: "not_ready",
    total_events: input.events.length,
    last_event_type: lastEventType,
    safe_wave: safeWaveFromEvents(input.events),
    failures,
    timeline,
    trust,
    event_apply_state: eventApplyState,
    apply_readiness: null,
    execution_explanation: null,
    operational_maturity: null,
    state: null,
    state_blocker: input.state_error ?? null
  };
}

function runStatusFromV2(status: WaygentRunStateV2["status"]): RunStatus {
  if (status === "initializing") return "pending";
  if (status === "applying") return "running";
  return status;
}

function statusFromEvents(events: AgentLensEvent[], trustStatus: string): RunStatus {
  if (events.some((event) => event.event_type === "runway.apply_completed")) return "applied";
  if (events.some((event) => event.outcome === "blocked")) return "blocked";
  if (events.some((event) => event.outcome === "failed")) return "failed";
  return trustStatus === "trusted" ? "completed" : "running";
}

function safeWaveFromEvents(events: AgentLensEvent[]): string[] {
  const selected = [...events].reverse().find((event) => event.event_type === "runway.safe_wave_selected");
  const safeWave = selected?.payload.safe_wave;
  return Array.isArray(safeWave) ? safeWave.map(String) : [];
}
