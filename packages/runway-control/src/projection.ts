import type { DecisionPacket } from "@waygent/contracts";
import { computeSafeWave, createDecisionPacket } from "./scheduler";
import type { CandidateGateState, DurableProjection, TaskGraph } from "./types";

export function buildDurableProjection(graph: TaskGraph): DurableProjection {
  const wave = computeSafeWave(graph);
  const blocked = wave.withheld.find((item) => item.reason === "failure_barrier") ?? null;
  const packet = blocked ? createDecisionPacket(graph.tasks.get(blocked.task_id)!, [`task:${blocked.task_id}`]) : null;
  const allApplied = [...graph.tasks.values()].every((task) => task.status === "APPLIED");
  return {
    ready_tasks: [...graph.tasks.values()].filter((task) => task.status === "READY").map((task) => task.id),
    safe_wave: wave.ready,
    withheld_tasks: wave.withheld,
    blocked_node: blocked?.task_id ?? null,
    projection_status: allApplied ? "complete" : blocked ? "blocked" : "ready",
    next_automatic_action: wave.ready.length > 0 ? "dispatch_safe_wave" : null,
    required_human_decision: packet
  };
}

export function mergeCandidate(state: CandidateGateState): CandidateGateState {
  if (!state.reviewed || !state.verified) {
    return { ...state, failure_class: "verification_failed", merged: false };
  }
  return {
    ...state,
    merged: true,
    checkpoint_ref: state.checkpoint_ref ?? `checkpoint_${state.task_id}_${state.candidate_id}`
  };
}

export function explicitApply(sourceDirty: boolean, state: CandidateGateState): DecisionPacket | null {
  if (sourceDirty) {
    return {
      schema: "runway.decision_packet.v1",
      task_id: state.task_id,
      failure_class: "needs_rebase",
      evidence_refs: [`candidate:${state.candidate_id}`],
      allowed_actions: ["clean_source_checkout", "retry_apply"],
      blocked_actions: ["apply_dirty_source"],
      resume_input_shape: { source_clean: "boolean" },
      summary: "Explicit apply refuses a dirty source checkout"
    };
  }
  if (!state.merged) {
    return {
      schema: "runway.decision_packet.v1",
      task_id: state.task_id,
      failure_class: "merge_conflict",
      evidence_refs: [`candidate:${state.candidate_id}`],
      allowed_actions: ["merge_selected_candidate"],
      blocked_actions: ["apply_unmerged_candidate"],
      resume_input_shape: { merged: "boolean" },
      summary: "Candidate must be merged before apply"
    };
  }
  return null;
}
