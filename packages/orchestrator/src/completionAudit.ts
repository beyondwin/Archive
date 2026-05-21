import type { WaygentRunStateV2 } from "@waygent/contracts";
import { readCheckpointManifest, validateCheckpointManifest } from "./checkpointArtifacts";

export interface CompletionAuditInput {
  state: WaygentRunStateV2;
  required_checks: string[];
  verification_evidence: Array<Record<string, unknown>>;
  review_evidence: Array<Record<string, unknown>>;
  prompt_to_artifact_checklist: string[];
}

export function buildCompletionAudit(input: CompletionAuditInput): Record<string, unknown> {
  const taskResults: Array<Record<string, unknown> & { task_id: string; ok: boolean; reason?: string }> = Object.values(input.state.tasks).map((task) => {
    if (task.status !== "verified") {
      return { task_id: task.id, ok: false, reason: `task_${task.status}` };
    }
    if (task.checkpoint_refs.length === 0) {
      return { task_id: task.id, ok: false, reason: "missing_checkpoint" };
    }
    const checkpoint_results: Array<Record<string, unknown> & { ok: boolean }> = task.checkpoint_refs.map((ref) => {
      const validation = validateCheckpointManifest(input.state.run_root, ref);
      if (!validation.ok) return { task_id: task.id, checkpoint_ref: ref, ...validation };
      const manifest = readCheckpointManifest(input.state.run_root, ref);
      return {
        task_id: task.id,
        checkpoint_ref: ref,
        ...validation,
        dry_run_status: manifest.dry_run_status,
        dry_run_evidence_ref: manifest.dry_run_evidence_ref
      };
    });
    return {
      task_id: task.id,
      ok: checkpoint_results.some((result) => result.ok && result.dry_run_status === "passed"),
      checkpoint_results
    };
  });
  const checkpointEvidence = taskResults.flatMap((result) =>
    "checkpoint_results" in result ? result.checkpoint_results : [result]
  );
  const failed = taskResults.filter((result) => !result.ok);

  return {
    status: failed.length === 0 && taskResults.length > 0 ? "passed" : "failed",
    required_checks: input.required_checks,
    verification_evidence: input.verification_evidence,
    review_evidence: input.review_evidence,
    checkpoint_evidence: checkpointEvidence,
    state_reconciliation: { passed: false },
    prompt_to_artifact_checklist: input.prompt_to_artifact_checklist,
    residual_risk: failed.map((result) => `${result.task_id}:${"reason" in result ? result.reason : "checkpoint_not_ready"}`)
  };
}

export function hasApplyReadyCheckpoint(state: WaygentRunStateV2): boolean {
  if ((state.completion_audit as { status?: string } | null)?.status !== "passed") return false;
  return Object.values(state.tasks)
    .filter((task) => task.status === "verified")
    .every((task) =>
      task.checkpoint_refs.some((ref) => {
        if (!validateCheckpointManifest(state.run_root, ref).ok) return false;
        return readCheckpointManifest(state.run_root, ref).dry_run_status === "passed";
      })
    );
}
