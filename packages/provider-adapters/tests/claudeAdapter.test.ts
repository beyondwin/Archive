import { describe, expect, test } from "bun:test";
import { ClaudeProviderAdapter, normalizeProcessOutput } from "../src";

describe("Claude adapter normalization", () => {
  test("executes a configured process and normalizes its worker result", async () => {
    const script = `
      const prompt = await new Response(Bun.stdin.stream()).text();
      console.log(JSON.stringify({
        summary: "claude ran " + prompt.includes("demo"),
        changed_files: ["b.ts"],
        evidence: { prompt_length: prompt.length }
      }));
    `;

    const result = await new ClaudeProviderAdapter({ executable: process.execPath, args: ["-e", script] }).run({
      task_id: "task_demo",
      candidate_id: "candidate_demo",
      prompt: "demo"
    });

    expect(result.status).toBe("completed");
    expect(result.summary).toBe("claude ran true");
    expect(result.changed_files).toEqual(["b.ts"]);
    expect(result.evidence).toMatchObject({ provider: "claude" });
  });

  test("classifies malformed output", () => {
    expect(normalizeProcessOutput("claude", "task_demo", "candidate_demo", { exitCode: 0, stdout: "not-json", stderr: "" }).failure_class).toBe(
      "malformed_result"
    );
  });

  test("normalizes Claude JSON result envelopes with fenced worker JSON", () => {
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: JSON.stringify({
        type: "result",
        result: '```json\n{"summary":"claude envelope done","changed_files":["d.ts"],"evidence":{"command":"claude"}}\n```'
      }),
      stderr: ""
    });

    expect(result.summary).toBe("claude envelope done");
    expect(result.changed_files).toEqual(["d.ts"]);
  });

  test("describes the process boundary without direct AgentLens writes", () => {
    expect(new ClaudeProviderAdapter({ executable: "claude" }).describe()).toEqual({
      provider: "claude",
      execution: "process",
      direct_agentlens_writes: false
    });
  });

  test("classifies an unavailable Claude executable as an adapter crash", async () => {
    const result = await new ClaudeProviderAdapter({ executable: "__missing_claude_for_test__" }).run({
      task_id: "task_demo",
      candidate_id: "candidate_demo",
      prompt: "demo"
    });
    expect(result.status).toBe("failed");
    expect(result.failure_class).toBe("adapter_crashed");
  });
});
