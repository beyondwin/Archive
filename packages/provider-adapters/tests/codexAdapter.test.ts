import { describe, expect, test } from "bun:test";
import { CodexProviderAdapter, normalizeProcessOutput } from "../src";

describe("Codex adapter normalization", () => {
  test("executes a configured process and normalizes its worker result", async () => {
    const script = `
      const prompt = await new Response(Bun.stdin.stream()).text();
      console.log(JSON.stringify({
        summary: "codex ran " + prompt.includes("demo"),
        changed_files: ["a.ts"],
        evidence: { prompt_length: prompt.length }
      }));
    `;

    const result = await new CodexProviderAdapter({ executable: process.execPath, args: ["-e", script] }).run({
      task_id: "task_demo",
      candidate_id: "candidate_demo",
      prompt: "demo"
    });

    expect(result.status).toBe("completed");
    expect(result.summary).toBe("codex ran true");
    expect(result.changed_files).toEqual(["a.ts"]);
    expect(result.evidence).toMatchObject({ provider: "codex" });
  });

  test("normalizes fake CLI output", () => {
    const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: JSON.stringify({ summary: "done", changed_files: ["a.ts"], evidence: { command: "codex" } }),
      stderr: ""
    });
    expect(result.changed_files).toEqual(["a.ts"]);
  });

  test("normalizes Codex JSONL result envelopes", () => {
    const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: [
        JSON.stringify({ type: "started" }),
        JSON.stringify({
          type: "result",
          result: JSON.stringify({ summary: "codex envelope done", changed_files: ["c.ts"], evidence: { command: "codex" } })
        })
      ].join("\n"),
      stderr: ""
    });

    expect(result.summary).toBe("codex envelope done");
    expect(result.changed_files).toEqual(["c.ts"]);
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

  test("classifies an unavailable Codex executable as an adapter crash", async () => {
    const result = await new CodexProviderAdapter({ executable: "__missing_codex_for_test__" }).run({
      task_id: "task_demo",
      candidate_id: "candidate_demo",
      prompt: "demo"
    });
    expect(result.status).toBe("failed");
    expect(result.failure_class).toBe("adapter_crashed");
  });
});
