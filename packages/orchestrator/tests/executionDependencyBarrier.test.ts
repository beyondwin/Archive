import { describe, expect, test } from "bun:test";
import type { ParsedWaygentPlan } from "../src/planParser";
import { applyExecutionDependencyBarriers } from "../src/executionDependencyBarrier";

const plan: ParsedWaygentPlan = {
  tasks: [
    {
      id: "task_core",
      title: "Core",
      dependencies: [],
      file_claims: [{ path: "fixthis-compose-core/src/main/kotlin/SourceMatcher.kt", mode: "owned" }],
      risk: "medium",
      verification_commands: ['./gradlew :fixthis-compose-core:test --tests "*SourceMatcherTest" --no-daemon'],
      instructions: []
    },
    {
      id: "task_mcp",
      title: "MCP",
      dependencies: [],
      file_claims: [{ path: "fixthis-mcp/src/main/kotlin/FeedbackQueueFormatter.kt", mode: "owned" }],
      risk: "medium",
      verification_commands: ['./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --no-daemon'],
      instructions: []
    },
    {
      id: "task_final",
      title: "Final",
      dependencies: [],
      file_claims: [{ path: "docs/reference/source-matching.md", mode: "owned" }],
      risk: "low",
      verification_commands: ["./gradlew test"],
      instructions: []
    }
  ]
};

describe("execution dependency barriers", () => {
  test("adds broad Gradle verification dependencies after module edits", () => {
    const result = applyExecutionDependencyBarriers(plan);

    expect(result.plan.tasks.find((task) => task.id === "task_final")?.dependencies).toEqual([
      "task_core",
      "task_mcp"
    ]);
    expect(result.barriers).toContainEqual({
      task_id: "task_final",
      depends_on: ["task_core", "task_mcp"],
      reason: "broad_gradle_verification",
      detail: "./gradlew test reads modules touched by earlier tasks"
    });
  });

  test("keeps independent module-local Gradle tasks parallel", () => {
    const result = applyExecutionDependencyBarriers({
      tasks: plan.tasks.slice(0, 2)
    });

    expect(result.plan.tasks.map((task) => task.dependencies)).toEqual([[], []]);
    expect(result.barriers).toEqual([]);
  });

  test("does not make broad Gradle verification depend on future module tasks", () => {
    const result = applyExecutionDependencyBarriers({
      tasks: [
        {
          id: "task_final_first",
          title: "Final first",
          dependencies: [],
          file_claims: [{ path: "docs/reference/source-matching.md", mode: "owned" }],
          risk: "low",
          verification_commands: ["./gradlew test"],
          instructions: []
        },
        {
          id: "task_later_module",
          title: "Later module",
          dependencies: [],
          file_claims: [{ path: "fixthis-mcp/src/main/kotlin/FeedbackQueueFormatter.kt", mode: "owned" }],
          risk: "medium",
          verification_commands: ['./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --no-daemon'],
          instructions: []
        }
      ]
    });

    expect(result.plan.tasks[0]?.dependencies).toEqual([]);
    expect(result.barriers).toEqual([]);
  });
});
