import { describe, expect, test } from "bun:test";
import { canCreateMutableWorktree, createDecisionPacket, retryRecommendation } from "../src";

describe("recovery policy", () => {
  test("returns bounded retry recommendation", () => {
    expect(
      retryRecommendation({
        id: "task_demo",
        dependencies: [],
        file_claims: [],
        resource_locks: [],
        risk: "medium",
        status: "READY",
        latest_failure_class: "adapter_crashed",
        retry_count: 0,
        max_retries: 1
      })
    ).toBe("retry");
  });

  test("creates decision packet and blocks worktree creation outside safe wave", () => {
    const task = {
      id: "task_demo",
      dependencies: [],
      file_claims: [],
      resource_locks: [],
      risk: "medium" as const,
      status: "READY" as const,
      latest_failure_class: "missing_checkpoint" as const
    };
    expect(createDecisionPacket(task).blocked_actions).toContain("create_mutable_worktree_without_safe_wave");
    expect(canCreateMutableWorktree(task, [])).toBe(false);
  });
});
