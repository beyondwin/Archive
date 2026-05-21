import { describe, expect, test } from "bun:test";
import { ClaudeProviderAdapter, normalizeProcessOutput } from "../src";

describe("Claude adapter normalization", () => {
  test("classifies malformed output", () => {
    expect(normalizeProcessOutput("claude", "task_demo", "candidate_demo", { exitCode: 0, stdout: "not-json", stderr: "" }).failure_class).toBe(
      "malformed_result"
    );
  });

  test("describes the process boundary without direct AgentLens writes", () => {
    expect(new ClaudeProviderAdapter({ executable: "claude" }).describe()).toEqual({
      provider: "claude",
      execution: "process",
      direct_agentlens_writes: false
    });
  });

  test("does not execute a live Claude process by default", async () => {
    const result = await new ClaudeProviderAdapter().run({ task_id: "task_demo", candidate_id: "candidate_demo", prompt: "demo" });
    expect(result.status).toBe("blocked");
    expect(result.failure_class).toBe("needs_infra_fix");
  });
});
