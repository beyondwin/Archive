import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
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

  test("accepts applied/waived method audit arrays from live Codex worker results", () => {
    const runRoot = mkdtempSync(join(tmpdir(), "waygent-method-evidence-policy-"));
    writeFileSync(join(runRoot, "worker.json"), JSON.stringify({
      schema: "runway.worker_result.v1",
      task_id: "task_demo",
      candidate_id: "candidate_task_demo",
      status: "completed",
      changed_files: ["src/demo.ts"],
      summary: "done",
      evidence: {
        method_audit: {
          applied: [
            {
              method: "verification-before-completion",
              evidence: "Ran required verification.",
              commands_run: [{ command: "bun test", exit_code: 0 }]
            }
          ],
          waived: []
        }
      }
    }));

    expect(validateMethodEvidenceForApply({
      require_method_evidence: true,
      state: {
        ...minimalState(),
        run_root: runRoot,
        provider_attempts: [{
          attempt_id: "attempt_demo",
          task_id: "task_demo",
          worker_result_ref: "worker.json"
        }]
      } as never
    })).toMatchObject({
      status: "passed",
      policies: {
        task_demo: {
          method_audit_status: "present"
        }
      }
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
