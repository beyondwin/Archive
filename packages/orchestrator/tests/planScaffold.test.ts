import { describe, expect, test } from "bun:test";
import { parseWaygentPlan } from "../src/planParser";
import { scaffoldWaygentTask } from "../src/planScaffold";

describe("Waygent plan scaffold", () => {
  test("creates an executable waygent-task block from explicit fields", () => {
    const markdown = scaffoldWaygentTask({
      id: "task_reliability",
      title: "Implement reliability hardening",
      dependencies: [],
      file_claims: [
        { path: "packages/orchestrator/src/verification.ts", mode: "owned" },
        { path: "packages/orchestrator/tests/verification.test.ts", mode: "owned" }
      ],
      risk: "high",
      verify: ["bun test packages/orchestrator/tests/verification.test.ts"]
    });

    expect(markdown).toContain("```yaml waygent-task");
    expect(parseWaygentPlan(markdown).tasks[0]).toMatchObject({
      id: "task_reliability",
      risk: "high"
    });
  });

  test("rejects scaffold requests without explicit file claims", () => {
    expect(() => scaffoldWaygentTask({
      id: "task_bad",
      title: "Bad scaffold",
      dependencies: [],
      file_claims: [],
      risk: "low",
      verify: ["printf bad"]
    })).toThrow("file claims required");
  });
});
