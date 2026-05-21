export interface WorktreeApplyRequest {
  run_id: string;
  source_dirty: boolean;
  checkpoint_ref: string;
}

export function buildWorktreeBranch(runId: string, taskId: string): string {
  return `waygent/${runId}/${taskId}`;
}

export interface ApplyGuardInput {
  sourceDirty: boolean;
  merged: boolean;
  candidate_id: string;
  task_id: string;
}

export interface ApplyGuard {
  can_apply: boolean;
  reason: "ready" | "dirty_source_checkout" | "candidate_not_merged";
  candidate_id: string;
  task_id: string;
}

export function buildApplyGuard(input: ApplyGuardInput): ApplyGuard {
  if (input.sourceDirty) {
    return { can_apply: false, reason: "dirty_source_checkout", candidate_id: input.candidate_id, task_id: input.task_id };
  }
  if (!input.merged) {
    return { can_apply: false, reason: "candidate_not_merged", candidate_id: input.candidate_id, task_id: input.task_id };
  }
  return { can_apply: true, reason: "ready", candidate_id: input.candidate_id, task_id: input.task_id };
}

export function validateExplicitApply(request: WorktreeApplyRequest): { allowed: boolean; reason: string } {
  if (request.source_dirty) return { allowed: false, reason: "source checkout is dirty" };
  if (!request.checkpoint_ref) return { allowed: false, reason: "checkpoint required" };
  return { allowed: true, reason: "apply may proceed" };
}
