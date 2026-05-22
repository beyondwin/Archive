import { describe, expect, test } from "bun:test";
import { validateMethodEvidenceForApply } from "../src/evidencePolicy";

describe("apply method evidence policy", () => {
  test("stays off by default", () => {
    expect(validateMethodEvidenceForApply({ require_method_evidence: false, state: minimalState() }).status).toBe("passed");
  });

  test("blocks apply when method evidence is required and missing", () => {
    expect(validateMethodEvidenceForApply({ require_method_evidence: true, state: minimalState() })).toMatchObject({
      status: "blocked",
      reason: "method_evidence_missing"
    });
  });
});

function minimalState() {
  return {
    tasks: {
      task_demo: {
        id: "task_demo",
        status: "verified",
        file_claims: [{ path: "src/demo.ts", mode: "owned" }],
        attempts: ["attempt_demo"]
      }
    },
    provider_attempts: [{
      attempt_id: "attempt_demo",
      task_id: "task_demo",
      worker_result_ref: null
    }],
    verification: [{ task_id: "task_demo", status: "passed" }]
  } as never;
}
