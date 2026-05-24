import { existsSync, readFileSync } from "node:fs";
import type { FailureClass, WaygentRunStateTaskV2, WaygentRunStateV2 } from "@waygent/contracts";
import { sha256 } from "@waygent/lens-store";
import { readCheckpointManifest, resolveRunArtifactPath, validateCheckpointManifest } from "./checkpointArtifacts";
import { validateMethodEvidenceForApply } from "./evidencePolicy";
import { shouldReviewTask } from "./reviewGate";
import { taskRequiresCheckpoint } from "./taskCheckpointPolicy";

export type TerminalInvariantCode =
  | "completion_audit_missing"
  | "completion_audit_not_passed"
  | "completed_with_failed_completion_audit"
  | "finished_without_completed_status"
  | "required_task_missing"
  | "required_task_not_verified"
  | "checkpoint_missing"
  | "checkpoint_not_apply_ready"
  | "checkpoint_dry_run_evidence_missing"
  | "combined_apply_evidence_missing"
  | "combined_apply_evidence_failed"
  | "combined_apply_evidence_artifact_missing"
  | "combined_apply_patch_missing"
  | "combined_apply_patch_drift"
  | "state_reconciliation_missing"
  | "state_reconciliation_failed"
  | "residual_risk_present"
  | "review_evidence_missing"
  | "method_evidence_missing";

export interface TerminalInvariantBlocker {
  code: TerminalInvariantCode;
  type: "artifact_missing" | "state_drift";
  severity: "blocking";
  failure_class: "artifact_missing" | "state_drift";
  message: string;
  task_id?: string;
  artifact_ref?: string;
}

export interface TerminalCompletionInvariantReport {
  passed: boolean;
  blockers: TerminalInvariantBlocker[];
}

export function evaluateTerminalCompletionInvariant(state: WaygentRunStateV2): TerminalCompletionInvariantReport {
  const blockers: TerminalInvariantBlocker[] = [];
  const audit = objectRecord(state.completion_audit);

  if (!audit) {
    blockers.push(drift("completion_audit_missing", "terminal completion requires a completion audit"));
  } else {
    if (state.status === "completed" && audit.status === "failed") {
      blockers.push(drift(
        "completed_with_failed_completion_audit",
        "completed run cannot be paired with a failed completion audit"
      ));
    }
    if (audit.status !== "passed") {
      blockers.push(drift("completion_audit_not_passed", "terminal completion requires completion_audit.status=passed"));
    }
    checkCombinedApplyEvidence(state, audit, blockers);
    checkStateReconciliation(audit, blockers);
    checkResidualRisk(audit, blockers);
  }

  if (state.lifecycle_outcome === "finished" && state.status !== "completed" && state.status !== "applied") {
    blockers.push(drift("finished_without_completed_status", "finished lifecycle outcome requires completed or applied run status"));
  }

  const tasks = Object.values(state.tasks);
  if (tasks.length === 0) {
    blockers.push(drift("required_task_missing", "terminal completion requires at least one required task"));
  }
  for (const task of tasks) {
    if (task.status !== "verified" && task.status !== "applied") {
      blockers.push(drift(
        "required_task_not_verified",
        `terminal completion requires ${task.id} to be verified`,
        undefined,
        task.id
      ));
      continue;
    }
    checkTaskCheckpoint(state, task, blockers);
  }

  for (const task of requiredReviewTasks(state)) {
    if (!hasReviewEvidence(state, audit, task.id)) {
      blockers.push(drift(
        "review_evidence_missing",
        `terminal completion requires review evidence for ${task.id}`,
        undefined,
        task.id
      ));
    }
  }

  const methodEvidence = validateMethodEvidenceForApply({
    state,
    require_method_evidence: state.method_evidence_required ?? false
  });
  for (const taskId of methodEvidence.missing_task_ids) {
    blockers.push(drift(
      "method_evidence_missing",
      `terminal completion requires method evidence or an allowlisted waiver for ${taskId}`,
      undefined,
      taskId
    ));
  }

  return { passed: blockers.length === 0, blockers };
}

function checkTaskCheckpoint(
  state: WaygentRunStateV2,
  task: WaygentRunStateTaskV2,
  blockers: TerminalInvariantBlocker[]
): void {
  if (!taskRequiresCheckpoint(task)) return;
  if (task.checkpoint_refs.length === 0) {
    blockers.push(missing("checkpoint_missing", `${task.id} has no apply-ready checkpoint reference`, undefined, task.id));
    return;
  }

  let sawExistingCheckpoint = false;
  for (const checkpointRef of task.checkpoint_refs) {
    const validation = validateCheckpointManifest(state.run_root, checkpointRef);
    if (!validation.ok) continue;
    sawExistingCheckpoint = true;
    const manifest = readCheckpointManifest(state.run_root, checkpointRef);
    if (manifest.dry_run_status !== "passed") continue;
    if (!manifest.dry_run_evidence_ref || !artifactExists(state.run_root, manifest.dry_run_evidence_ref)) {
      blockers.push(missing(
        "checkpoint_dry_run_evidence_missing",
        `${task.id} checkpoint dry-run evidence is missing`,
        manifest.dry_run_evidence_ref ?? checkpointRef,
        task.id
      ));
      return;
    }
    return;
  }

  blockers.push((sawExistingCheckpoint ? drift : missing)(
    "checkpoint_not_apply_ready",
    `${task.id} has no checkpoint with a passed dry-run`,
    task.checkpoint_refs[0],
    task.id
  ));
}

function checkCombinedApplyEvidence(
  state: WaygentRunStateV2,
  audit: Record<string, unknown>,
  blockers: TerminalInvariantBlocker[]
): void {
  const combined = objectRecord(audit.combined_apply_evidence);
  if (!combined) {
    blockers.push(missing("combined_apply_evidence_missing", "terminal completion requires combined apply evidence"));
    return;
  }
  if (combined.status !== "passed") {
    blockers.push(drift("combined_apply_evidence_failed", "terminal completion requires passed combined apply evidence"));
  }
  const evidenceRef = typeof combined.evidence_ref === "string" ? combined.evidence_ref : null;
  if (!evidenceRef || !artifactExists(state.run_root, evidenceRef)) {
    blockers.push(missing(
      "combined_apply_evidence_artifact_missing",
      "combined apply dry-run evidence is missing",
      evidenceRef ?? undefined
    ));
  }
  const patchRef = typeof combined.patch_ref === "string" ? combined.patch_ref : null;
  if (!patchRef || !artifactExists(state.run_root, patchRef)) {
    blockers.push(missing(
      "combined_apply_patch_missing",
      "combined apply patch is missing",
      patchRef ?? undefined
    ));
    return;
  }
  const patch = readFileSync(resolveRunArtifactPath(state.run_root, patchRef));
  if (typeof combined.patch_sha256 === "string" && sha256(patch) !== combined.patch_sha256) {
    blockers.push(drift("combined_apply_patch_drift", "combined apply patch digest does not match completion audit", patchRef));
  }
  if (typeof combined.patch_byte_length === "number" && patch.byteLength !== combined.patch_byte_length) {
    blockers.push(drift("combined_apply_patch_drift", "combined apply patch byte length does not match completion audit", patchRef));
  }
}

function checkStateReconciliation(audit: Record<string, unknown>, blockers: TerminalInvariantBlocker[]): void {
  const reconciliation = objectRecord(audit.state_reconciliation);
  if (!reconciliation) {
    blockers.push(drift("state_reconciliation_missing", "terminal completion requires state reconciliation evidence"));
    return;
  }
  const unrepaired = Array.isArray(reconciliation.unrepaired_blockers)
    ? reconciliation.unrepaired_blockers
    : [];
  if (reconciliation.passed !== true || unrepaired.length > 0) {
    blockers.push(drift("state_reconciliation_failed", "terminal completion requires passed state reconciliation"));
  }
}

function checkResidualRisk(audit: Record<string, unknown>, blockers: TerminalInvariantBlocker[]): void {
  const residualRisk = audit.residual_risk;
  if (!Array.isArray(residualRisk) || residualRisk.length > 0) {
    blockers.push(drift("residual_risk_present", "terminal completion requires empty completion_audit.residual_risk"));
  }
}

function requiredReviewTasks(state: WaygentRunStateV2): WaygentRunStateTaskV2[] {
  const mode = typeof state.provider_profile.execution_mode === "string"
    ? state.provider_profile.execution_mode
    : "multi-agent";
  if (mode !== "multi-agent") return [];
  return Object.values(state.tasks).filter((task) =>
    (task.status === "verified" || task.status === "applied") &&
    shouldReviewTask({
      risk: task.risk,
      file_claims: task.file_claims,
      previous_failure_count: task.latest_failure_class ? 1 : 0
    })
  );
}

function hasReviewEvidence(state: WaygentRunStateV2, audit: Record<string, unknown> | null, taskId: string): boolean {
  const auditEvidence = Array.isArray(audit?.review_evidence) ? audit.review_evidence : [];
  return [...auditEvidence, ...state.reviews].some((candidate) => {
    const record = objectRecord(candidate);
    if (!record) return false;
    const recordTaskId = typeof record.task_id === "string" ? record.task_id : null;
    if (recordTaskId && recordTaskId !== taskId) return false;
    const status = typeof record.status === "string"
      ? record.status
      : typeof record.outcome === "string"
        ? record.outcome
        : typeof record.verdict === "string"
          ? record.verdict
          : null;
    return status === "passed" || status === "approved" || status === "success" || status === "pass";
  });
}

function artifactExists(runRoot: string, ref: string): boolean {
  return existsSync(resolveRunArtifactPath(runRoot, ref));
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function missing(
  code: TerminalInvariantCode,
  message: string,
  artifact_ref?: string,
  task_id?: string
): TerminalInvariantBlocker {
  return record("artifact_missing", code, message, artifact_ref, task_id);
}

function drift(
  code: TerminalInvariantCode,
  message: string,
  artifact_ref?: string,
  task_id?: string
): TerminalInvariantBlocker {
  return record("state_drift", code, message, artifact_ref, task_id);
}

function record(
  failure_class: Extract<FailureClass, "artifact_missing" | "state_drift">,
  code: TerminalInvariantCode,
  message: string,
  artifact_ref?: string,
  task_id?: string
): TerminalInvariantBlocker {
  return {
    code,
    type: failure_class,
    severity: "blocking",
    failure_class,
    message,
    ...(artifact_ref ? { artifact_ref } : {}),
    ...(task_id ? { task_id } : {})
  };
}
