import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { reviewEvidenceMissing, reviewEvidencePolicy } from "../src/reviewEvidence";
import { baseV2State } from "./support/runStateFixture";

describe("review evidence policy", () => {
  test("requires review for high-risk tasks", () => {
    const state = baseV2State({ root: mkdtempSync(join(tmpdir(), "waygent-review-evidence-")), run_id: "run_review_policy" });
    state.tasks.task_a.risk = "high";
    state.tasks.task_a.status = "verified";
    state.tasks.task_a.checkpoint_refs = ["checkpoint/task_a.json"];

    expect(reviewEvidencePolicy(state)).toMatchObject({ required: true, reason: "high_risk_task" });
    expect(reviewEvidenceMissing({ state, review_evidence: [] })).toBe("high_risk_task");
  });

  test("requires review after recovery attempts", () => {
    const state = baseV2State({ root: mkdtempSync(join(tmpdir(), "waygent-review-recovery-")), run_id: "run_review_recovery" });
    state.recovery.push({
      task_id: "task_a",
      failure_class: "verification_failed",
      action: "retry_with_evidence",
      attempt_number: 1
    });

    expect(reviewEvidencePolicy(state)).toMatchObject({ required: true, reason: "recovery_attempted" });
    expect(reviewEvidenceMissing({ state, review_evidence: [] })).toBe("recovery_attempted");
  });

  test("accepts present review evidence", () => {
    const state = baseV2State({ root: mkdtempSync(join(tmpdir(), "waygent-review-present-")), run_id: "run_review_present" });
    state.method_evidence_required = true;

    expect(reviewEvidenceMissing({ state, review_evidence: [{ verdict: "pass" }] })).toBeNull();
  });
});
