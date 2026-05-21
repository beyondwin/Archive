import type { WaygentRunStateV2 } from "@waygent/contracts";
import { existsSync, readFileSync } from "node:fs";
import { sha256 } from "@waygent/lens-store";
import {
  type CombinedCheckpointPatchResult,
  readCheckpointManifest,
  resolveRunArtifactPath,
  validateCheckpointManifest
} from "./checkpointArtifacts";

export interface CompletionAuditInput {
  state: WaygentRunStateV2;
  required_checks: string[];
  verification_evidence: Array<Record<string, unknown>>;
  review_evidence: Array<Record<string, unknown>>;
  combined_apply_evidence?: CombinedCheckpointPatchResult;
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
  const combinedApplyOk = input.combined_apply_evidence?.status === "passed";
  const residualRisk = failed.map((result) => `${result.task_id}:${"reason" in result ? result.reason : "checkpoint_not_ready"}`);
  if (!combinedApplyOk) {
    residualRisk.push(`combined_apply:${input.combined_apply_evidence?.reason ?? "missing_verified_checkpoint"}`);
  }

  return {
    status: failed.length === 0 && taskResults.length > 0 && combinedApplyOk ? "passed" : "failed",
    required_checks: input.required_checks,
    verification_evidence: input.verification_evidence,
    review_evidence: input.review_evidence,
    checkpoint_evidence: checkpointEvidence,
    ...(input.combined_apply_evidence ? { combined_apply_evidence: input.combined_apply_evidence } : {}),
    state_reconciliation: { passed: false },
    prompt_to_artifact_checklist: input.prompt_to_artifact_checklist,
    residual_risk: residualRisk
  };
}

export function hasApplyReadyCheckpoint(state: WaygentRunStateV2): boolean {
  if (state.drift.unrepaired_blockers.length > 0) return false;
  const audit = state.completion_audit as {
    status?: string;
    combined_apply_evidence?: { status?: string; patch_ref?: string };
  } | null;
  if (audit?.status !== "passed") return false;
  if (!audit.combined_apply_evidence) return false;
  const evidence = audit.combined_apply_evidence as {
    status?: string;
    patch_ref?: string;
    patch_sha256?: string;
    patch_byte_length?: number;
  };
  if (evidence.status !== "passed" || !evidence.patch_ref) return false;
  const patchPath = resolveRunArtifactPath(state.run_root, evidence.patch_ref);
  if (!existsSync(patchPath)) return false;
  const patch = readFileSync(patchPath);
  if (evidence.patch_sha256 && sha256(patch) !== evidence.patch_sha256) return false;
  if (typeof evidence.patch_byte_length === "number" && patch.byteLength !== evidence.patch_byte_length) return false;
  return Object.values(state.tasks)
    .filter((task) => task.status === "verified")
    .every((task) =>
      task.checkpoint_refs.some((ref) => {
        if (!validateCheckpointManifest(state.run_root, ref).ok) return false;
        return readCheckpointManifest(state.run_root, ref).dry_run_status === "passed";
      })
    );
}
