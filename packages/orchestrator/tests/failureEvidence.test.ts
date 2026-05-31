import { describe, expect, test } from "bun:test";
import type { WorkerResult } from "@waygent/contracts";
import { classifyFailureEvidence } from "../src/failureEvidence";

const completedWorkerWithPatch: WorkerResult = {
  schema: "runway.worker_result.v1",
  task_id: "task_a",
  candidate_id: "candidate_task_a",
  status: "completed",
  changed_files: ["a.txt"],
  summary: "Worker changed a.txt",
  evidence: {
    patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
    patch_sha256: "a".repeat(64),
    patch_byte_length: 12
  }
};

describe("classifyFailureEvidence", () => {
  test("routes verification failure with patch evidence to repair", () => {
    expect(
      classifyFailureEvidence({
        task_id: "task_a",
        failure_class: "verification_failed",
        worker_result: completedWorkerWithPatch,
        provider_attempt_ref: "artifacts/provider/attempt_task_a_1.stdout.txt",
        repair_budget: { max_attempts: 2, current: 0 }
      })
    ).toEqual({
      kind: "recoverable_patch",
      task_id: "task_a",
      failure_class: "verification_failed",
      patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
      changed_files: ["a.txt"],
      evidence_refs: [
        "artifacts/provider/attempt_task_a_1.stdout.txt",
        "artifacts/worker/task_a/attempt_1_patch.diff"
      ],
      recommended_action: "dispatch_repair"
    });
  });

  test("routes malformed result with safe captured diff to salvage then review", () => {
    expect(
      classifyFailureEvidence({
        task_id: "task_b",
        failure_class: "malformed_result",
        captured_patch_ref: "artifacts/worker/task_b/attempt_1_patch.diff",
        changed_files: ["b.txt"],
        provider_attempt_ref: "artifacts/provider/attempt_task_b_1.stdout.txt",
        diff_scope_safe: true,
        repair_budget: { max_attempts: 2, current: 0 }
      })
    ).toMatchObject({
      kind: "recoverable_patch",
      task_id: "task_b",
      failure_class: "malformed_result",
      patch_ref: "artifacts/worker/task_b/attempt_1_patch.diff",
      changed_files: ["b.txt"],
      recommended_action: "salvage_then_review"
    });
  });

  test("blocks malformed result when captured diff is unsafe", () => {
    expect(
      classifyFailureEvidence({
        task_id: "task_b",
        failure_class: "malformed_result",
        captured_patch_ref: "artifacts/worker/task_b/attempt_1_patch.diff",
        changed_files: ["../escape.txt"],
        provider_attempt_ref: "artifacts/provider/attempt_task_b_1.stdout.txt",
        diff_scope_safe: false,
        repair_budget: { max_attempts: 2, current: 0 }
      })
    ).toEqual({
      kind: "needs_operator_decision",
      task_id: "task_b",
      failure_class: "malformed_result",
      reason: "unsafe_patch_scope",
      evidence_refs: [
        "artifacts/provider/attempt_task_b_1.stdout.txt",
        "artifacts/worker/task_b/attempt_1_patch.diff"
      ]
    });
  });

  test("asks for operator decision when no recoverable patch exists", () => {
    expect(
      classifyFailureEvidence({
        task_id: "task_c",
        failure_class: "adapter_crashed",
        provider_attempt_ref: "artifacts/provider/attempt_task_c_1.stderr.txt",
        repair_budget: { max_attempts: 2, current: 0 }
      })
    ).toEqual({
      kind: "needs_operator_decision",
      task_id: "task_c",
      failure_class: "adapter_crashed",
      reason: "missing_patch_evidence",
      evidence_refs: ["artifacts/provider/attempt_task_c_1.stderr.txt"]
    });
  });

  test("stops when repair budget is exhausted", () => {
    expect(
      classifyFailureEvidence({
        task_id: "task_a",
        failure_class: "verification_failed",
        worker_result: completedWorkerWithPatch,
        provider_attempt_ref: "artifacts/provider/attempt_task_a_1.stdout.txt",
        repair_budget: { max_attempts: 2, current: 2 }
      })
    ).toEqual({
      kind: "terminal_unrecoverable",
      task_id: "task_a",
      failure_class: "verification_failed",
      reason: "repair_budget_exhausted",
      evidence_refs: [
        "artifacts/provider/attempt_task_a_1.stdout.txt",
        "artifacts/worker/task_a/attempt_1_patch.diff"
      ]
    });
  });
});
