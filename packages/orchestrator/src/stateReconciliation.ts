import { existsSync } from "node:fs";
import { readRunStateV2, writeRunStateV2 } from "./runState";

export interface ReconciliationRecord {
  type: "artifact_missing" | "completed_task_missing_unit_manifest" | "finished_without_completion_audit";
  severity: "blocking" | "repairable";
  message: string;
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
    if (task.status === "verified" && task.task_packet_path && !existsSync(task.task_packet_path)) {
      records.push({
        type: "artifact_missing",
        severity: "blocking",
        message: `${task.id} task packet is missing`
      });
    }
    if (task.status === "verified" && !task.unit_manifest) {
      records.push({
        type: "completed_task_missing_unit_manifest",
        severity: "blocking",
        message: `${task.id} missing unit manifest`
      });
    }
  }

  if (state.lifecycle_outcome === "finished" && !state.completion_audit) {
    records.push({
      type: "finished_without_completion_audit",
      severity: "blocking",
      message: "finished run requires completion audit"
    });
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
