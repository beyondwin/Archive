import { join } from "node:path";

export interface WorktreeApplyRequest {
  run_id: string;
  source_dirty: boolean;
  checkpoint_ref: string;
}

export function buildWorktreeBranch(runId: string, taskId: string): string {
  return `waygent/${runId}/${taskId}`;
}

export interface PlannedWorktree {
  branch: string;
  path: string;
  source: string;
}

export interface WorktreeManifest extends PlannedWorktree {
  task_id: string;
  source_commit: string | null;
  cleanup_status: "active" | "removed" | "unknown";
}

export function planWorktree(options: {
  run_id: string;
  task_id: string;
  workspace: string;
  worktree_root: string;
}): PlannedWorktree {
  return {
    branch: buildWorktreeBranch(options.run_id, options.task_id),
    path: join(options.worktree_root, options.run_id, options.task_id),
    source: options.workspace
  };
}

export function buildWorktreeManifest(input: PlannedWorktree & { task_id: string; source_commit: string | null }): WorktreeManifest {
  return { ...input, cleanup_status: "active" };
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
