import { describe, expect, test } from "bun:test";
import { evaluateFinalOutputHooks, evaluatePreDispatchHooks } from "../src/runtimeHooks";

describe("runtime hooks", () => {
  test("denies dangerous pre-dispatch verification commands", () => {
    const result = evaluatePreDispatchHooks({
      enabled: true,
      task_id: "task_demo",
      commands: ["rm -rf dist"],
      file_claims: []
    });

    expect(result.status).toBe("denied");
    expect(result.denials[0]?.hook_id).toBe("dangerous_command");
  });

  test("validates final worker result shape", () => {
    expect(evaluateFinalOutputHooks({
      enabled: true,
      task_id: "task_demo",
      worker: { status: "completed" },
      stdout: "",
      stderr: ""
    }).status).toBe("denied");
  });

  function validWorker(overrides: Record<string, unknown> = {}) {
    return {
      schema: "runway.worker_result.v1",
      task_id: "task_demo",
      candidate_id: "candidate_task_demo",
      status: "completed",
      changed_files: [],
      summary: "",
      evidence: {},
      ...overrides
    };
  }

  test("ignores destructive command names quoted inside descriptive summary prose", () => {
    const worker = validWorker({
      summary: "Destructive command candidates (rm -rf, git reset --hard, git clean -fd) raise blocking findings.",
      evidence: { verification_commands: ["bun test packages/orchestrator/tests/intakeRecovery.test.ts"], notes: "rm -rf is mentioned as an example pattern, not a command we run." }
    });
    const stdout = JSON.stringify({ type: "result", result: JSON.stringify(worker) });

    const result = evaluateFinalOutputHooks({
      enabled: true,
      task_id: "task_demo",
      worker,
      stdout,
      stderr: ""
    });

    expect(result.status).toBe("passed");
    expect(result.denials).toEqual([]);
  });

  test("still denies dangerous commands in worker.evidence.verification_commands", () => {
    const worker = validWorker({
      summary: "Clean tests",
      evidence: { verification_commands: ["bun test", "rm -rf node_modules"] }
    });

    const result = evaluateFinalOutputHooks({
      enabled: true,
      task_id: "task_demo",
      worker,
      stdout: "",
      stderr: ""
    });

    expect(result.status).toBe("denied");
    expect(result.denials.map((denial) => denial.hook_id)).toContain("dangerous_output_command");
  });

  test("still denies dangerous patterns in stderr", () => {
    const worker = validWorker({ summary: "ok", evidence: { verification_commands: ["printf hi"] } });

    const result = evaluateFinalOutputHooks({
      enabled: true,
      task_id: "task_demo",
      worker,
      stdout: "",
      stderr: "+ rm -rf /tmp/x"
    });

    expect(result.status).toBe("denied");
    expect(result.denials.map((denial) => denial.hook_id)).toContain("dangerous_output_command");
  });

  test("falls back to broad stdout+stderr scan when worker shape is invalid", () => {
    const result = evaluateFinalOutputHooks({
      enabled: true,
      task_id: "task_demo",
      worker: { not_a_worker: true },
      stdout: "stdout includes rm -rf as a command",
      stderr: ""
    });

    expect(result.status).toBe("denied");
    expect(result.denials.map((denial) => denial.hook_id)).toEqual(
      expect.arrayContaining(["worker_result_shape", "dangerous_output_command"])
    );
  });
});
