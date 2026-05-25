import { describe, expect, test } from "bun:test";
import { selectRepairAction } from "../src/recoveryExecutor";

const PRIOR_OK = {
  schema: "runway.worker_result.v1" as const,
  task_id: "task_x",
  candidate_id: "cand_x",
  status: "completed" as const,
  changed_files: [],
  summary: "s",
  evidence: { patch_ref: "artifacts/worker/task_x/attempt_1_patch.diff", patch_sha256: "x", patch_byte_length: 1 }
};

describe("selectRepairAction", () => {
  test("dispatches repair when verification failed + completed worker_result + patch present + budget remaining", () => {
    const decision = selectRepairAction({
      failure_class: "verification_failed",
      prior_worker_result: PRIOR_OK,
      repair_budget: { max_attempts: 2, current: 0 }
    });
    expect(decision).toEqual({ action: "dispatch_repair", attempt_number: 1, max_attempts: 2 });
  });

  test("returns null when failure_class is not verification_failed", () => {
    expect(selectRepairAction({
      failure_class: "adapter_crashed",
      prior_worker_result: PRIOR_OK,
      repair_budget: { max_attempts: 2, current: 0 }
    })).toBeNull();
  });

  test("returns null when prior worker_result missing", () => {
    expect(selectRepairAction({
      failure_class: "verification_failed",
      prior_worker_result: null,
      repair_budget: { max_attempts: 2, current: 0 }
    })).toBeNull();
  });

  test("returns null when prior worker_result.status is not completed", () => {
    expect(selectRepairAction({
      failure_class: "verification_failed",
      prior_worker_result: { ...PRIOR_OK, status: "failed" },
      repair_budget: { max_attempts: 2, current: 0 }
    })).toBeNull();
  });

  test("returns null when patch_ref missing", () => {
    expect(selectRepairAction({
      failure_class: "verification_failed",
      prior_worker_result: { ...PRIOR_OK, evidence: {} },
      repair_budget: { max_attempts: 2, current: 0 }
    })).toBeNull();
  });

  test("returns request_decision when budget exhausted", () => {
    const decision = selectRepairAction({
      failure_class: "verification_failed",
      prior_worker_result: PRIOR_OK,
      repair_budget: { max_attempts: 2, current: 2 }
    });
    expect(decision).toEqual({ action: "request_decision", attempt_number: 3, max_attempts: 2 });
  });
});
