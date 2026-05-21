import { describe, expect, test } from "bun:test";
import { CodexProviderAdapter, normalizeProcessOutput } from "../src";

describe("Codex adapter normalization", () => {
  test("normalizes fake CLI output", () => {
    const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: JSON.stringify({ summary: "done", changed_files: ["a.ts"], evidence: { command: "codex" } }),
      stderr: ""
    });
    expect(result.changed_files).toEqual(["a.ts"]);
  });

  test("classifies crashes", () => {
    expect(normalizeProcessOutput("codex", "task_demo", "candidate_demo", { exitCode: 2, stdout: "", stderr: "boom" }).failure_class).toBe(
      "adapter_crashed"
    );
  });

  test("describes the process boundary without direct AgentLens writes", () => {
    expect(new CodexProviderAdapter({ executable: "codex" }).describe()).toEqual({
      provider: "codex",
      execution: "process",
      direct_agentlens_writes: false
    });
  });

  test("does not execute a live Codex process by default", async () => {
    const result = await new CodexProviderAdapter().run({ task_id: "task_demo", candidate_id: "candidate_demo", prompt: "demo" });
    expect(result.status).toBe("blocked");
    expect(result.failure_class).toBe("needs_infra_fix");
  });
});
