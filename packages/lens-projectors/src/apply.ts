import type { AgentLensEvent, ApplyReadinessProjection, WaygentRunStateV2 } from "@waygent/contracts";

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

export function projectApplyReadinessFromState(state: WaygentRunStateV2): ApplyReadinessProjection {
  if (state.apply.status === "applied") {
    return {
      status: "applied",
      reason: null,
      checkpoint_refs: checkpointRefsFromState(state),
      combined_patch_ref: combinedPatchRef(state),
      source: "run_state_v2"
    };
  }

  if (state.drift.unrepaired_blockers.length > 0) {
    return {
      status: "blocked",
      reason: "state_drift",
      checkpoint_refs: checkpointRefsFromState(state),
      combined_patch_ref: combinedPatchRef(state),
      source: "run_state_v2"
    };
  }

  const audit = state.completion_audit as {
    status?: string;
    combined_apply_evidence?: Record<string, unknown>;
  } | null;
  const combined = audit?.combined_apply_evidence;
  const refs = checkpointRefsFromCombined(combined) ?? checkpointRefsFromState(state);
  const patchRef = combinedPatchRef(state);
  const taskBlocker = activeCheckpointTaskBlocker(state);

  if (taskBlocker) {
    return {
      status: "blocked",
      reason: taskBlocker,
      checkpoint_refs: refs,
      combined_patch_ref: patchRef,
      source: "run_state_v2"
    };
  }

  if (audit?.status === "passed" && combined?.status === "passed" && patchRef && refs.length > 0) {
    return {
      status: "ready",
      reason: null,
      checkpoint_refs: refs,
      combined_patch_ref: patchRef,
      source: "run_state_v2"
    };
  }

  return {
    status: state.apply.status === "blocked" ? "blocked" : "not_ready",
    reason: state.apply.reason || "missing_apply_ready_evidence",
    checkpoint_refs: refs,
    combined_patch_ref: patchRef,
    source: "run_state_v2"
  };
}

function checkpointRefsFromState(state: WaygentRunStateV2): string[] {
  const refs = new Set<string>();
  for (const task of Object.values(state.tasks)) {
    for (const ref of task.checkpoint_refs) {
      if (ref.length > 0) refs.add(ref);
    }
  }
  return [...refs];
}

function checkpointRefsFromCombined(combined: Record<string, unknown> | undefined): string[] | null {
  const refs = combined?.checkpoint_refs;
  if (!Array.isArray(refs)) return null;
  const checkpointRefs = refs.filter((ref): ref is string => typeof ref === "string" && ref.length > 0);
  return checkpointRefs.length > 0 ? checkpointRefs : null;
}

function combinedPatchRef(state: WaygentRunStateV2): string | null {
  const combined = (state.completion_audit as {
    combined_apply_evidence?: { patch_ref?: unknown };
  } | null)?.combined_apply_evidence;
  return typeof combined?.patch_ref === "string" && combined.patch_ref.length > 0 ? combined.patch_ref : null;
}

function activeCheckpointTaskBlocker(state: WaygentRunStateV2): string | null {
  const task = Object.values(state.tasks).find((candidate) =>
    (candidate.status === "blocked" || candidate.status === "failed" || state.status === "blocked" || state.status === "failed") &&
    typeof candidate.latest_failure_class === "string" &&
    candidate.checkpoint_refs.length === 0
  );
  return typeof task?.latest_failure_class === "string" ? task.latest_failure_class : null;
}
