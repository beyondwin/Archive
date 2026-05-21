import type {
  AgentLensEvent,
  DogfoodEvidenceProjection,
  OperationalMaturityProjection,
  ProviderReadinessProjection,
  RuntimeCostProjection,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectApplyReadinessFromState } from "./apply";
import { projectDogfoodEvidenceFromState } from "./dogfoodEvidence";
import { projectProviderReadinessFromState } from "./providerReadiness";
import { projectRuntimeCostFromState } from "./runtimeCost";

export interface OperationalMaturityInput {
  state: WaygentRunStateV2;
  events: AgentLensEvent[];
}

export function projectOperationalMaturityFromState(input: OperationalMaturityInput): OperationalMaturityProjection {
  const projectionErrors: OperationalMaturityProjection["projection_errors"] = [];
  const applyReadiness = projectApplyReadinessFromState(input.state);
  const dogfoodEvidence = safeProject("dogfood_evidence", projectionErrors, () =>
    projectDogfoodEvidenceFromState(input), () => dogfoodProjectionError(input.state.run_id));
  const runtimeCost = safeProject("runtime_cost", projectionErrors, () =>
    projectRuntimeCostFromState({ state: input.state, dogfood_evidence: dogfoodEvidence }), () => runtimeCostProjectionError(input.state.run_id));
  const providerReadiness = safeProject("provider_readiness", projectionErrors, () =>
    projectProviderReadinessFromState({ state: input.state }), () => providerReadinessProjectionError(input.state.run_id));
  const hardBlocker = hardBlockerFromState(input.state, applyReadiness.reason);

  return {
    schema: "waygent.operational_maturity.v1",
    run_id: input.state.run_id,
    hard_blocker: hardBlocker,
    dogfood_evidence: dogfoodEvidence,
    runtime_cost: runtimeCost,
    provider_readiness: providerReadiness,
    apply_readiness: applyReadiness,
    next_action: nextAction({ hardBlocker, dogfoodEvidence, runtimeCost, providerReadiness }),
    projection_errors: projectionErrors
  };
}

function safeProject<T>(
  name: string,
  errors: OperationalMaturityProjection["projection_errors"],
  run: () => T,
  fallback: () => T
): T {
  try {
    return run();
  } catch (error) {
    errors.push({ projection: name, message: error instanceof Error ? error.message : String(error) });
    return fallback();
  }
}

function hardBlockerFromState(
  state: WaygentRunStateV2,
  applyReadinessReason: string | null
): OperationalMaturityProjection["hard_blocker"] {
  const task = Object.values(state.tasks).find((candidate) =>
    (candidate.status === "blocked" || candidate.status === "failed" || state.status === "blocked" || state.status === "failed") &&
    typeof candidate.latest_failure_class === "string" &&
    candidate.latest_failure_class.length > 0
  );
  if (task?.latest_failure_class) {
    return {
      task_id: task.id,
      failure_class: task.latest_failure_class,
      summary: `${task.id} blocked by ${task.latest_failure_class}`
    };
  }
  const drift = state.drift.unrepaired_blockers[0];
  const driftFailure = drift && typeof drift.failure_class === "string" ? drift.failure_class : null;
  const applyBlocker = state.apply.status === "blocked" ? state.apply.reason ?? applyReadinessReason : applyReadinessReason;
  const failureClass = driftFailure ?? applyBlocker;
  if (failureClass && state.status !== "completed") {
    return {
      task_id: null,
      failure_class: failureClass,
      summary: `run blocked by ${failureClass}`
    };
  }
  return null;
}

function nextAction(input: {
  hardBlocker: OperationalMaturityProjection["hard_blocker"];
  dogfoodEvidence: DogfoodEvidenceProjection;
  runtimeCost: RuntimeCostProjection;
  providerReadiness: ProviderReadinessProjection;
}): string {
  if (input.hardBlocker) return `Resolve ${input.hardBlocker.failure_class} before resume or apply.`;
  if (input.providerReadiness.status !== "ready" && input.providerReadiness.status !== "unknown") {
    return input.providerReadiness.recommended_next_action;
  }
  if (input.dogfoodEvidence.status !== "complete") {
    return "Run a dogfood check when evidence completeness is partial.";
  }
  return input.runtimeCost.recommended_next_actions[0] ?? "No active failure barrier and no trust-preserving optimization is recommended.";
}

function dogfoodProjectionError(runId: string): DogfoodEvidenceProjection {
  return {
    schema: "waygent.dogfood_evidence.v1",
    run_id: runId,
    status: "projection_error",
    dogfood_run_ref: null,
    checklist: [],
    missing_reasons: ["dogfood_evidence projection failed"],
    real_runtime_timestamps: false,
    explain_summary: null
  };
}

function runtimeCostProjectionError(runId: string): RuntimeCostProjection {
  return {
    schema: "waygent.runtime_cost.v1",
    run_id: runId,
    estimated_wave_count: 0,
    measured_wave_count: 0,
    parallelism_score: 0,
    serial_barriers: [],
    phase_totals: [],
    top_hotspots: [],
    fixed_costs: {},
    recommended_next_actions: ["Inspect projection errors before acting on runtime-cost guidance."]
  };
}

function providerReadinessProjectionError(runId: string): ProviderReadinessProjection {
  return {
    schema: "waygent.provider_readiness.v1",
    run_id: runId,
    provider: null,
    status: "unknown",
    command_summary: [],
    stderr_summary: null,
    failure_class: null,
    attempt_refs: [],
    recommended_next_action: "Inspect projection errors before acting on provider readiness."
  };
}
