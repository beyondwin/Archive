export interface WorktreeApplyRequest {
  run_id: string;
  source_dirty: boolean;
  checkpoint_ref: string;
}

export function validateExplicitApply(request: WorktreeApplyRequest): { allowed: boolean; reason: string } {
  if (request.source_dirty) return { allowed: false, reason: "source checkout is dirty" };
  if (!request.checkpoint_ref) return { allowed: false, reason: "checkpoint required" };
  return { allowed: true, reason: "apply may proceed" };
}
