import { existsSync, readFileSync } from "node:fs";
import type { FailureClass } from "@waygent/contracts";
import { readEvents, sha256 } from "@waygent/lens-store";
import { readCheckpointManifest, resolveRunArtifactPath, validateCheckpointManifest } from "./checkpointArtifacts";
import { readRunStateV2, writeRunStateV2 } from "./runState";

export interface ReconciliationRecord {
  type: "artifact_missing" | "state_drift";
  severity: "blocking";
  failure_class: "artifact_missing" | "state_drift";
  message: string;
  artifact_ref?: string;
  task_id?: string;
}

export interface ReconciliationReport {
  passed: boolean;
  records: ReconciliationRecord[];
  unrepaired_blockers: ReconciliationRecord[];
}

export function reconcileRunState(root: string, runId: string): ReconciliationReport {
  const state = readRunStateV2(root, runId);
  const records: ReconciliationRecord[] = [];

  for (const task of Object.values(state.tasks)) {
    if (task.task_packet_path) {
      if (!existsSync(task.task_packet_path)) {
        records.push(missing(`${task.id} task packet is missing`, task.task_packet_path, task.id));
      } else if (task.task_packet_sha256 && sha256(readFileSync(task.task_packet_path)) !== task.task_packet_sha256) {
        records.push(drift(`${task.id} task packet digest does not match state`, task.task_packet_path, task.id));
      }
    }
    if (task.status === "verified" && !task.unit_manifest) {
      records.push(drift(`${task.id} missing unit manifest`, undefined, task.id));
    }
    if (task.status === "verified" && task.checkpoint_refs.length === 0) {
      records.push(missing(`${task.id} has no checkpoint manifest`, undefined, task.id));
    }
    for (const checkpointRef of task.checkpoint_refs) {
      const validation = validateCheckpointManifest(state.run_root, checkpointRef);
      if (!validation.ok) {
        records.push(checkpointFailure(checkpointRef, validation.reason ?? "checkpoint_manifest_missing", task.id));
        continue;
      }
      const manifest = readCheckpointManifest(state.run_root, checkpointRef);
      if (!manifest.dry_run_evidence_ref || !artifactExists(state.run_root, manifest.dry_run_evidence_ref)) {
        records.push(missing(`${task.id} checkpoint dry-run evidence is missing`, manifest.dry_run_evidence_ref ?? checkpointRef, task.id));
      }
    }
  }

  for (const attempt of state.provider_attempts) {
    for (const ref of [
      attempt.stdin_ref,
      attempt.stdout_ref,
      attempt.stderr_ref,
      attempt.event_stream_ref,
      attempt.worker_result_ref
    ]) {
      if (ref && !artifactExists(state.run_root, ref)) {
        records.push(missing(`${attempt.task_id} provider artifact is missing`, ref, attempt.task_id));
      }
    }
  }

  for (const record of state.verification) {
    const taskId = typeof record.task_id === "string" ? record.task_id : undefined;
    const ref = record.kernel_result_ref;
    if (typeof ref === "string" && !artifactExists(state.run_root, ref)) {
      records.push(missing(`${taskId ?? "unknown task"} verification kernel result is missing`, ref, taskId));
    }
  }

  if (state.lifecycle_outcome === "finished" && !state.completion_audit) {
    records.push(drift("finished run requires completion audit"));
  }

  const completionAudit = state.completion_audit as {
    status?: string;
    combined_apply_evidence?: {
      status?: string;
      checkpoint_refs?: unknown;
      patch_ref?: string;
      patch_sha256?: string;
      patch_byte_length?: number;
      evidence_ref?: string;
    };
  } | null;
  if (state.status === "completed" && completionAudit?.status !== "passed") {
    records.push(drift("completed run requires passed completion audit"));
  }
  const combined = completionAudit?.combined_apply_evidence;
  if (state.status === "completed" && completionAudit?.status === "passed" && !combined) {
    records.push(missing("completed apply-ready run requires combined apply evidence"));
  }
  if (combined) {
    if (combined.evidence_ref && !artifactExists(state.run_root, combined.evidence_ref)) {
      records.push(missing("combined apply dry-run evidence is missing", combined.evidence_ref));
    }
    if (combined.status === "passed") {
      if (!combined.patch_ref || !artifactExists(state.run_root, combined.patch_ref)) {
        records.push(missing("combined apply patch is missing", combined.patch_ref));
      } else {
        const patch = readFileSync(resolveRunArtifactPath(state.run_root, combined.patch_ref));
        if (combined.patch_sha256 && sha256(patch) !== combined.patch_sha256) {
          records.push(drift("combined apply patch digest does not match completion audit", combined.patch_ref));
        }
        if (typeof combined.patch_byte_length === "number" && patch.byteLength !== combined.patch_byte_length) {
          records.push(drift("combined apply patch byte length does not match completion audit", combined.patch_ref));
        }
      }
    }
  }

  if (!existsSync(state.event_journal_path)) {
    records.push(missing("event journal is missing", state.event_journal_path));
  } else if (state.status === "completed") {
    try {
      const events = readEvents(state.event_journal_path);
      if (!events.some((event) => event.event_type === "lens.trust_report_updated")) {
        records.push(drift("completed run is missing terminal trust report event", state.event_journal_path));
      }
    } catch {
      records.push(drift("event journal cannot be read", state.event_journal_path));
    }
  }

  const unrepaired_blockers = records.filter((record) => record.severity === "blocking");
  const driftRecords: Array<Record<string, unknown>> = records.map((record) => ({ ...record }));
  const driftBlockers: Array<Record<string, unknown>> = unrepaired_blockers.map((record) => ({ ...record }));
  writeRunStateV2(root, {
    ...state,
    drift: {
      last_checked_at: new Date().toISOString(),
      records: driftRecords,
      unrepaired_blockers: driftBlockers
    }
  });
  return { passed: unrepaired_blockers.length === 0, records, unrepaired_blockers };
}

function artifactExists(runRoot: string, ref: string): boolean {
  return existsSync(resolveRunArtifactPath(runRoot, ref));
}

function missing(message: string, artifact_ref?: string, task_id?: string): ReconciliationRecord {
  return record("artifact_missing", message, artifact_ref, task_id);
}

function drift(message: string, artifact_ref?: string, task_id?: string): ReconciliationRecord {
  return record("state_drift", message, artifact_ref, task_id);
}

function record(
  failure_class: Extract<FailureClass, "artifact_missing" | "state_drift">,
  message: string,
  artifact_ref?: string,
  task_id?: string
): ReconciliationRecord {
  return {
    type: failure_class,
    severity: "blocking",
    failure_class,
    message,
    ...(artifact_ref ? { artifact_ref } : {}),
    ...(task_id ? { task_id } : {})
  };
}

function checkpointFailure(
  checkpointRef: string,
  reason: "checkpoint_manifest_missing" | "checkpoint_patch_missing" | "checkpoint_digest_mismatch",
  taskId: string
): ReconciliationRecord {
  if (reason === "checkpoint_digest_mismatch") {
    return drift(`${taskId} checkpoint digest does not match manifest`, checkpointRef, taskId);
  }
  return missing(`${taskId} checkpoint artifact is missing`, checkpointRef, taskId);
}
