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
});
