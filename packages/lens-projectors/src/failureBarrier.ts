import type { FailureBarrierProjection, WaygentRunStateV2 } from "@waygent/contracts";

const FAILURE_CLASS_TO_BARRIER: Record<string, NonNullable<FailureBarrierProjection["barrier_type"]>> = {
  verification_failed: "verification_fail",
  command_not_found: "verification_fail",
  dirty_source_checkout: "env_blocker",
  environment_blocker: "env_blocker",
  dependency_missing: "env_blocker",
  needs_plan_fix: "spec_blocker",
  needs_split: "spec_blocker",
  malformed_result: "quality_fail",
  diff_scope_failed: "quality_fail",
  review_changes_requested: "quality_fail",
  review_rejected: "quality_fail",
  missing_checkpoint: "checkpoint_missing",
  artifact_missing: "evidence_missing"
};

export function projectFailureBarrierFromState(state: WaygentRunStateV2): FailureBarrierProjection {
  const budgetPaused = state.apply.reason === "budget_paused" ||
    state.recovery.some((record) => record.reason === "budget_paused" || record.failure_class === "budget_paused");
  if (budgetPaused) {
    return barrier(state, "budget_paused", null, "budget_paused", "budget cap paused execution", [`state:${state.state_path}`]);
  }
  const taskFailure = Object.values(state.tasks).find((task) => typeof task.latest_failure_class === "string" && task.latest_failure_class.length > 0);
  if (taskFailure?.latest_failure_class) {
    const barrierType = FAILURE_CLASS_TO_BARRIER[taskFailure.latest_failure_class] ?? "ambiguity";
    return barrier(
      state,
      barrierType,
      taskFailure.id,
      taskFailure.latest_failure_class,
      `task ${taskFailure.id} failed by ${taskFailure.latest_failure_class}`,
      [`state:${state.state_path}`, `task:${taskFailure.id}`]
    );
  }
  if (state.apply.reason === "method_evidence_missing") {
    return barrier(state, "evidence_missing", null, "method_evidence_missing", "method evidence is missing", [`state:${state.state_path}`]);
  }
  return barrier(state, null, null, null, null, []);
}

function barrier(
  state: WaygentRunStateV2,
  barrierType: FailureBarrierProjection["barrier_type"],
  taskId: string | null,
  failureClass: string | null,
  reason: string | null,
  evidenceRefs: string[]
): FailureBarrierProjection {
  return {
    schema: "waygent.failure_barrier.v1",
    run_id: state.run_id,
    barrier_type: barrierType,
    task_id: taskId,
    failure_class: failureClass,
    reason,
    evidence_refs: evidenceRefs
  };
}
