import { describe, expect, test } from "bun:test";
import { ClaudeProviderAdapter, normalizeProcessOutput, providerProcessArgs } from "../src";

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

    expect(result.worker.status).toBe("completed");
    expect(result.worker.summary).toBe("claude ran true");
    expect(result.worker.changed_files).toEqual(["b.ts"]);
    expect(result.worker.evidence).toMatchObject({ provider: "claude" });
    expect(result.process.exit_code).toBe(0);
    expect(result.process.stdout).toContain("claude ran true");
  });

  test("classifies malformed output", () => {
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", { exitCode: 0, stdout: "not-json", stderr: "raw err" });

    expect(result.worker.failure_class).toBe("malformed_result");
    expect(result.process).toMatchObject({
      stdout: "not-json",
      stderr: "raw err",
      exit_code: 0,
      timed_out: false
    });
  });

  test("normalizes Claude JSON result envelopes with fenced worker JSON", () => {
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: JSON.stringify({
        type: "result",
        result: '```json\n{"status":"success","summary":"claude envelope done","changed_files":["d.ts"],"evidence":{"command":"claude"}}\n```'
      }),
      stderr: ""
    });

    expect(result.worker.status).toBe("completed");
    expect(result.worker.summary).toBe("claude envelope done");
    expect(result.worker.changed_files).toEqual(["d.ts"]);
    expect(result.process.stdout).toContain("```json");
  });

  test("preserves provider supplied failure_class from fenced Claude JSON", () => {
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: [
        "Claude summary:",
        '```json\n{"status":"failed","failure_class":"review_changes_requested","summary":"review found issues","changed_files":[],"evidence":{"command":"claude"}}\n```'
      ].join("\n"),
      stderr: "review stderr"
    });

    expect(result.worker.status).toBe("failed");
    expect(result.worker.failure_class).toBe("review_changes_requested");
    expect(result.process.stderr).toBe("review stderr");
  });

  test("describes the process boundary without direct AgentLens writes", () => {
    expect(new ClaudeProviderAdapter({ executable: "claude" }).describe()).toEqual({
      provider: "claude",
      execution: "process",
      direct_agentlens_writes: false
    });
  });

  test("prepends --model and --effort to claude args when set", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "claude", args: ["-p", "--output-format", "json"], model: "opus", effort: "high" },
      "/tmp/work",
      { task_id: "t", candidate_id: "c", prompt: "p" }
    );
    expect(args.slice(0, 4)).toEqual(["--model", "opus", "--effort", "high"]);
    expect(args).toContain("--permission-mode");
    expect(args).toContain("acceptEdits");
  });

  test("respects user-supplied --model and does not duplicate", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "claude", args: ["--model", "sonnet", "-p"], model: "opus" },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p" }
    );
    expect(args.filter((arg) => arg === "--model").length).toBe(1);
    expect(args).toContain("sonnet");
    expect(args).not.toContain("opus");
  });

  test("omits --model when option not set", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "claude", args: ["-p"] },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p" }
    );
    expect(args).not.toContain("--model");
  });

  test("does not prepend Claude CLI flags for custom executables", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: process.execPath, args: ["worker.mjs"], model: "opus", effort: "high" },
      "/tmp/work",
      { task_id: "t", candidate_id: "c", prompt: "p" }
    );
    expect(args).toEqual(["worker.mjs"]);
  });

  test("recognizes absolute Claude CLI executable paths", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "/usr/local/bin/claude", args: ["-p"], model: "opus", effort: "high" },
      "/tmp/work",
      { task_id: "t", candidate_id: "c", prompt: "p" }
    );
    expect(args).toContain("--model");
    expect(args).toContain("opus");
    expect(args).toContain("--effort");
    expect(args).toContain("high");
    expect(args).toContain("--add-dir");
  });

  test("classifies an unavailable Claude executable as an adapter crash", async () => {
    const result = await new ClaudeProviderAdapter({ executable: "__missing_claude_for_test__" }).run({
      task_id: "task_demo",
      candidate_id: "candidate_demo",
      prompt: "demo"
    });
    expect(result.worker.status).toBe("failed");
    expect(result.worker.failure_class).toBe("adapter_crashed");
    expect(result.process.exit_code).toBeNull();
    expect(result.process.stderr).toContain("failed to start");
  });
});
