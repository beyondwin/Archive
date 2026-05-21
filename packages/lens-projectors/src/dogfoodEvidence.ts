import type {
  AgentLensEvent,
  DogfoodChecklistStatus,
  DogfoodEvidenceChecklistItem,
  DogfoodEvidenceProjection,
  ExecutionExplanationProjection,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectApplyReadinessFromState } from "./apply";
import { projectExecutionExplanationFromState } from "./executionExplanation";

export interface DogfoodEvidenceInput {
  state: WaygentRunStateV2;
  events: AgentLensEvent[];
  explanation?: ExecutionExplanationProjection;
}

export function projectDogfoodEvidenceFromState(input: DogfoodEvidenceInput): DogfoodEvidenceProjection {
  const explanation = input.explanation ?? projectExecutionExplanationFromState(input.state);
  const checklist = [
    eventJournalItem(input.events),
    providerAttemptsItem(input.state),
    verificationRecordsItem(input.state),
    artifactIndexItem(input.state),
    taskPhaseTimingsItem(input.state),
    waveTimingItem(input.state),
    runtimeTimestampsItem(input.state, input.events),
    explainSummaryItem(explanation),
    readinessArtifactRefsItem(input.state, explanation)
  ];
  const missingReasons = checklist
    .filter((item) => item.status === "missing" || item.status === "stale" || item.status === "error")
    .map((item) => item.reason ?? `${item.item} ${item.status}`);
  const presentCount = checklist.filter((item) => item.status === "present" || item.status === "not_applicable").length;
  const status = missingReasons.length === 0
    ? "complete"
    : presentCount === 0
      ? "missing"
      : "partial";

  return {
    schema: "waygent.dogfood_evidence.v1",
    run_id: input.state.run_id,
    status,
    dogfood_run_ref: dogfoodRunRef(input.state),
    checklist,
    missing_reasons: missingReasons,
    real_runtime_timestamps: checklist.find((item) => item.item === "runtime_timestamps")?.status === "present",
    explain_summary: explanation.status_summary
  };
}

function eventJournalItem(events: AgentLensEvent[]): DogfoodEvidenceChecklistItem {
  return item({
    item: "event_journal",
    present: events.length > 0,
    refs: events.slice(0, 5).map((event) => event.event_id),
    missingReason: "event_journal missing"
  });
}

function providerAttemptsItem(state: WaygentRunStateV2): DogfoodEvidenceChecklistItem {
  const executedTaskCount = Object.values(state.tasks).filter((task) => task.status !== "pending" && task.status !== "ready").length;
  if (executedTaskCount === 0) {
    return item({ item: "provider_attempts", status: "not_applicable", reason: "no executed tasks", refs: [] });
  }
  return item({
    item: "provider_attempts",
    present: state.provider_attempts.length > 0,
    refs: state.provider_attempts.map((attempt) => attempt.attempt_id),
    missingReason: "provider_attempts missing"
  });
}

function verificationRecordsItem(state: WaygentRunStateV2): DogfoodEvidenceChecklistItem {
  return item({
    item: "verification_records",
    present: state.verification.length > 0,
    refs: state.verification.map((record) => stringRecordValue(record, "verification_id")).filter(Boolean),
    missingReason: "verification_records missing"
  });
}

function artifactIndexItem(state: WaygentRunStateV2): DogfoodEvidenceChecklistItem {
  const refs = state.artifact_index?.map((artifact) => artifact.ref) ?? [];
  return item({
    item: "artifact_index",
    present: refs.length > 0,
    refs,
    missingReason: "artifact_index missing"
  });
}

function taskPhaseTimingsItem(state: WaygentRunStateV2): DogfoodEvidenceChecklistItem {
  const executedTasks = Object.values(state.tasks).filter((task) => task.status !== "pending" && task.status !== "ready");
  if (executedTasks.length === 0) {
    return item({ item: "task_phase_timings", status: "not_applicable", reason: "no executed tasks", refs: [] });
  }
  const missing = executedTasks
    .filter((task) => !hasRequiredTaskTimings(task))
    .map((task) => task.id);
  return item({
    item: "task_phase_timings",
    present: missing.length === 0,
    refs: executedTasks.flatMap((task) => (task.phase_timings ?? []).map((timing) => `${task.id}:${timing.phase}`)),
    missingReason: missing.length > 0 ? `task_phase_timings missing for ${missing.join(", ")}` : "task_phase_timings missing"
  });
}

function waveTimingItem(state: WaygentRunStateV2): DogfoodEvidenceChecklistItem {
  const waves = state.safe_waves.filter((wave) => wave.ready.length > 0);
  if (waves.length === 0) {
    return item({ item: "wave_timing", status: "not_applicable", reason: "no safe waves executed", refs: [] });
  }
  const missing = waves.filter((wave) => !wave.timing || typeof wave.concurrency !== "number").map((wave) => wave.wave_id);
  return item({
    item: "wave_timing",
    present: missing.length === 0,
    refs: waves.map((wave) => wave.wave_id),
    missingReason: missing.length > 0 ? `wave_timing missing for ${missing.join(", ")}` : "wave_timing missing"
  });
}

function runtimeTimestampsItem(state: WaygentRunStateV2, events: AgentLensEvent[]): DogfoodEvidenceChecklistItem {
  const timestamps = [
    state.timestamps.started_at,
    state.timestamps.updated_at,
    state.timestamps.completed_at,
    ...events.map((event) => event.occurred_at),
    ...Object.values(state.tasks).flatMap((task) => (task.phase_timings ?? []).flatMap((timing) => [timing.started, timing.completed]))
  ].filter((value): value is string => typeof value === "string" && value.length > 0);
  const unique = new Set(timestamps);
  return item({
    item: "runtime_timestamps",
    present: timestamps.length > 0 && unique.size > 1,
    refs: [...unique].slice(0, 5),
    missingReason: "runtime_timestamps missing or fixed"
  });
}

function explainSummaryItem(explanation: ExecutionExplanationProjection): DogfoodEvidenceChecklistItem {
  const precise = explanation.status_summary.length > 0 && !/\bunknown\b/i.test(explanation.status_summary);
  return item({
    item: "explain_summary",
    present: precise,
    refs: [explanation.schema],
    missingReason: "explain_summary missing precise blocker or no-blocker statement"
  });
}

function readinessArtifactRefsItem(
  state: WaygentRunStateV2,
  explanation: ExecutionExplanationProjection
): DogfoodEvidenceChecklistItem {
  const readiness = projectApplyReadinessFromState(state);
  if (readiness.status !== "ready") {
    return item({ item: "readiness_artifact_refs", status: "not_applicable", reason: "apply readiness is not ready", refs: [] });
  }
  const indexedRefs = new Set((state.artifact_index ?? []).map((artifact) => artifact.ref));
  const refs = explanation.artifact_health.readiness_artifact_refs;
  const missingRefs = refs.filter((ref) => !indexedRefs.has(ref));
  return item({
    item: "readiness_artifact_refs",
    present: refs.length > 0 && missingRefs.length === 0,
    refs,
    missingReason: missingRefs.length > 0
      ? `readiness_artifact_refs missing from artifact_index: ${missingRefs.join(", ")}`
      : "readiness_artifact_refs missing"
  });
}

function hasRequiredTaskTimings(task: WaygentRunStateV2["tasks"][string]): boolean {
  const phases = new Set((task.phase_timings ?? []).map((timing) => timing.phase));
  const hasExecution = phases.has("provider") && phases.has("verification") && phases.has("total");
  const hasCheckpointOrBlocker = phases.has("checkpoint") || phases.has("checkpoint_dry_run") || Boolean(task.latest_failure_class) || task.status === "blocked" || task.status === "failed";
  return hasExecution && hasCheckpointOrBlocker;
}

function item(input: {
  item: string;
  present?: boolean;
  refs: string[];
  missingReason?: string;
  status?: DogfoodChecklistStatus;
  reason?: string | null;
}): DogfoodEvidenceChecklistItem {
  if (input.status) {
    return {
      item: input.item,
      status: input.status,
      refs: input.refs,
      reason: input.reason ?? null
    };
  }
  return {
    item: input.item,
    status: input.present ? "present" : "missing",
    refs: input.refs,
    reason: input.present ? null : input.missingReason ?? `${input.item} missing`
  };
}

function stringRecordValue(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === "string" ? value : "";
}

function dogfoodRunRef(state: WaygentRunStateV2): string | null {
  const value = state.provider_profile.dogfood_run_ref ?? state.provider_profile.dogfoodRunRef;
  return typeof value === "string" && value.length > 0 ? value : null;
}
