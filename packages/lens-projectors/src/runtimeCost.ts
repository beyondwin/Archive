import type {
  DogfoodEvidenceProjection,
  ExecutionBarrier,
  ExecutionCostHotspot,
  ExecutionPhaseName,
  RuntimeCostProjection,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectExecutionExplanationFromState } from "./executionExplanation";

export interface RuntimeCostInput {
  state: WaygentRunStateV2;
  dogfood_evidence?: DogfoodEvidenceProjection;
}

export function projectRuntimeCostFromState(input: RuntimeCostInput): RuntimeCostProjection {
  const explanation = projectExecutionExplanationFromState(input.state);
  const phaseTotals = phaseTotalsFromState(input.state);
  const fixedCosts = Object.fromEntries(phaseTotals.map((total) => [total.phase, total.duration_ms])) as Partial<Record<ExecutionPhaseName, number>>;
  const taskCount = Math.max(1, Object.keys(input.state.tasks).length);
  const measuredWaveCount = input.state.safe_waves.length;
  const averageReadyPerWave = measuredWaveCount > 0
    ? input.state.safe_waves.reduce((sum, wave) => sum + wave.ready.length, 0) / measuredWaveCount
    : 0;

  return {
    schema: "waygent.runtime_cost.v1",
    run_id: input.state.run_id,
    estimated_wave_count: Math.max(1, input.state.safe_waves.length),
    measured_wave_count: measuredWaveCount,
    parallelism_score: roundScore(Math.min(1, averageReadyPerWave / taskCount)),
    serial_barriers: serialBarriers(explanation.barriers),
    phase_totals: phaseTotals,
    top_hotspots: explanation.cost_hotspots,
    fixed_costs: fixedCosts,
    recommended_next_actions: runtimeRecommendations(explanation.recommended_next_actions, phaseTotals, input.dogfood_evidence)
  };
}

function serialBarriers(barriers: ExecutionBarrier[]): RuntimeCostProjection["serial_barriers"] {
  const grouped = new Map<ExecutionBarrier["category"], { task_ids: Set<string>; reasons: Set<string> }>();
  for (const barrier of barriers) {
    const group = grouped.get(barrier.category) ?? { task_ids: new Set<string>(), reasons: new Set<string>() };
    group.task_ids.add(barrier.task_id);
    group.reasons.add(barrier.reason);
    grouped.set(barrier.category, group);
  }
  return [...grouped.entries()].map(([category, group]) => ({
    category,
    count: group.task_ids.size,
    task_ids: [...group.task_ids],
    reasons: [...group.reasons]
  }));
}

function phaseTotalsFromState(state: WaygentRunStateV2): RuntimeCostProjection["phase_totals"] {
  const totals = new Map<ExecutionPhaseName, { duration_ms: number; task_ids: Set<string>; wave_ids: Set<string> }>();
  for (const wave of state.safe_waves) {
    if (typeof wave.timing?.duration_ms === "number") {
      addPhaseTotal(totals, "wave", wave.timing.duration_ms, null, wave.wave_id);
    }
  }
  for (const task of Object.values(state.tasks)) {
    for (const timing of task.phase_timings ?? []) {
      if (typeof timing.duration_ms === "number") {
        addPhaseTotal(totals, timing.phase, timing.duration_ms, task.id, null);
      }
    }
  }
  return [...totals.entries()]
    .map(([phase, total]) => ({
      phase,
      duration_ms: total.duration_ms,
      task_ids: [...total.task_ids],
      wave_ids: [...total.wave_ids]
    }))
    .sort((a, b) => b.duration_ms - a.duration_ms);
}

function addPhaseTotal(
  totals: Map<ExecutionPhaseName, { duration_ms: number; task_ids: Set<string>; wave_ids: Set<string> }>,
  phase: ExecutionPhaseName,
  durationMs: number,
  taskId: string | null,
  waveId: string | null
): void {
  const total = totals.get(phase) ?? { duration_ms: 0, task_ids: new Set<string>(), wave_ids: new Set<string>() };
  total.duration_ms += durationMs;
  if (taskId) total.task_ids.add(taskId);
  if (waveId) total.wave_ids.add(waveId);
  totals.set(phase, total);
}

function runtimeRecommendations(
  explanationRecommendations: string[],
  phaseTotals: RuntimeCostProjection["phase_totals"],
  dogfoodEvidence: DogfoodEvidenceProjection | undefined
): string[] {
  const recommendations = new Set(explanationRecommendations);
  const topPhase = phaseTotals[0]?.phase;
  const verificationTotal = phaseTotals.find((total) => total.phase === "verification")?.duration_ms ?? 0;
  const providerTotal = phaseTotals.find((total) => total.phase === "provider")?.duration_ms ?? 0;
  if (topPhase === "verification") {
    recommendations.add("Inspect verification environment cost before changing provider concurrency.");
  }
  if (verificationTotal > 0 && verificationTotal >= providerTotal) {
    recommendations.add("Inspect verification environment cost before changing provider concurrency.");
  }
  if (topPhase === "provider") {
    recommendations.add("Inspect provider process cost before increasing safe-wave concurrency.");
  }
  if (dogfoodEvidence && dogfoodEvidence.status !== "complete") {
    recommendations.add("Run a dogfood check when evidence completeness is partial.");
  }
  if (recommendations.size === 0) {
    recommendations.add("No trust-preserving optimization is recommended from the recorded evidence.");
  }
  return [...recommendations];
}

function roundScore(value: number): number {
  return Math.round(value * 100) / 100;
}
