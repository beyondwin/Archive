import type {
  ArtifactHealthSummary,
  ExecutionBarrier,
  ExecutionCostHotspot,
  ExecutionExplanationProjection,
  WaygentRunStateV2
} from "@waygent/contracts";

const readinessRefKeys = ["checkpoint_refs", "patch_ref", "evidence_ref"] as const;

export function projectExecutionExplanationFromState(state: WaygentRunStateV2): ExecutionExplanationProjection {
  const barriers = state.safe_waves.flatMap((wave) =>
    wave.withheld.map((item): ExecutionBarrier => ({
      task_id: item.task_id,
      reason: item.reason,
      detail: item.detail ?? item.reason,
      wave_id: wave.wave_id,
      category: barrierCategory(item.reason)
    }))
  );
  const costHotspots = costHotspotsFromState(state);
  const artifactHealth = artifactHealthFromState(state);
  return {
    schema: "waygent.execution_explanation.v1",
    run_id: state.run_id,
    status_summary: statusSummary(state, barriers, costHotspots),
    waves: state.safe_waves.map((wave) => ({
      wave_id: wave.wave_id,
      ready: wave.ready,
      concurrency: wave.concurrency ?? null,
      duration_ms: wave.timing?.duration_ms ?? null,
      withheld: wave.withheld.map((item) => ({
        task_id: item.task_id,
        reason: item.reason,
        detail: item.detail ?? null
      }))
    })),
    barriers,
    cost_hotspots: costHotspots,
    artifact_health: artifactHealth,
    recommended_next_actions: recommendations(barriers, costHotspots, artifactHealth)
  };
}

function barrierCategory(reason: string): ExecutionBarrier["category"] {
  if (reason.includes("dependency")) return "dependency";
  if (reason.includes("checkpoint")) return "checkpoint";
  if (reason.includes("claim")) return "file_claim";
  if (reason.includes("risk")) return "risk";
  if (reason.includes("failure")) return "failure";
  if (reason.includes("dirty") || reason.includes("source")) return "source";
  return "unknown";
}

function costHotspotsFromState(state: WaygentRunStateV2): ExecutionCostHotspot[] {
  const hotspots: ExecutionCostHotspot[] = [];
  for (const wave of state.safe_waves) {
    if (typeof wave.timing?.duration_ms === "number") {
      hotspots.push({ scope: "wave", phase: "wave", duration_ms: wave.timing.duration_ms, task_id: null, wave_id: wave.wave_id });
    }
  }
  for (const task of Object.values(state.tasks)) {
    for (const timing of task.phase_timings ?? []) {
      if (typeof timing.duration_ms === "number") {
        hotspots.push({ scope: "task", phase: timing.phase, duration_ms: timing.duration_ms, task_id: task.id, wave_id: null });
      }
    }
  }
  return hotspots.sort((a, b) => b.duration_ms - a.duration_ms).slice(0, 5);
}

function artifactHealthFromState(state: WaygentRunStateV2): ArtifactHealthSummary {
  const readinessRefs = readinessRefsFromCompletionAudit(state.completion_audit);
  const driftRecords = state.drift.records.filter((record) => String(record.failure_class ?? record.type ?? "").includes("drift"));
  const missingRecords = state.drift.records.filter((record) => String(record.failure_class ?? record.type ?? "").includes("missing"));
  return {
    indexed_count: state.artifact_index?.length ?? 0,
    missing_count: missingRecords.length,
    drift_count: driftRecords.length,
    readiness_artifact_refs: readinessRefs
  };
}

function readinessRefsFromCompletionAudit(audit: Record<string, unknown> | null): string[] {
  const combined = audit?.combined_apply_evidence;
  if (!combined || typeof combined !== "object") return [];
  const refs = new Set<string>();
  for (const key of readinessRefKeys) {
    const value = (combined as Record<string, unknown>)[key];
    if (typeof value === "string" && value.length > 0) refs.add(value);
    if (Array.isArray(value)) {
      for (const ref of value) {
        if (typeof ref === "string" && ref.length > 0) refs.add(ref);
      }
    }
  }
  return [...refs];
}

function statusSummary(
  state: WaygentRunStateV2,
  barriers: ExecutionBarrier[],
  hotspots: ExecutionCostHotspot[]
): string {
  if (barriers.length > 0) return `${state.run_id} has ${barriers.length} scheduling barrier${barriers.length === 1 ? "" : "s"}.`;
  const hotspot = hotspots[0];
  if (hotspot) return `${state.run_id} spent most recorded time in ${hotspot.phase}.`;
  return `${state.run_id} has no recorded scheduling barriers.`;
}

function recommendations(
  barriers: ExecutionBarrier[],
  hotspots: ExecutionCostHotspot[],
  health: ArtifactHealthSummary
): string[] {
  const result = new Set<string>();
  if (barriers.some((barrier) => barrier.category === "file_claim")) {
    result.add("Split overlapping file claims or add dependencies so safe waves can stay parallel.");
  }
  if (barriers.some((barrier) => barrier.category === "risk")) {
    result.add("Reduce high-risk task scope before expecting wider safe waves.");
  }
  if (hotspots.some((hotspot) => hotspot.phase === "worktree_setup")) {
    result.add("Inspect worktree setup cost before changing provider concurrency.");
  }
  if (health.missing_count > 0 || health.drift_count > 0) {
    result.add("Repair missing or drifted artifacts before applying checkpoints.");
  }
  if (result.size === 0) result.add("No trust-preserving optimization is recommended from the recorded evidence.");
  return [...result];
}
