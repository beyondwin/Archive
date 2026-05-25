import { describe, expect, test } from "bun:test";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { CodexProviderAdapter, normalizeProcessOutput, providerProcessArgs } from "../src";

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

    expect(result.worker.status).toBe("completed");
    expect(result.worker.summary).toBe("codex ran true");
    expect(result.worker.changed_files).toEqual(["a.ts"]);
    expect(result.worker.evidence).toMatchObject({ provider: "codex" });
    expect(result.process).toMatchObject({
      stderr: "",
      exit_code: 0,
      timed_out: false,
      event_stream: null
    });
    expect(result.process.stdout).toContain("codex ran true");
    expect(result.process.started_at).toMatch(/\d{4}-\d{2}-\d{2}T/);
    expect(result.process.completed_at).toMatch(/\d{4}-\d{2}-\d{2}T/);
  });

  test("normalizes fake CLI output", () => {
    const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: JSON.stringify({ status: "completed", summary: "done", changed_files: ["a.ts"], evidence: { command: "codex" } }),
      stderr: ""
    });
    expect(result.worker.changed_files).toEqual(["a.ts"]);
    expect(result.process.stdout).toContain("done");
    expect(result.process.exit_code).toBe(0);
  });

  test("sets provider cwd and PWD from the adapter request", async () => {
    const script = `
      console.log(JSON.stringify({
        status: "completed",
        summary: "cwd checked",
        changed_files: [],
        evidence: { pwd: process.env.PWD, cwd: process.cwd() }
      }));
    `;
    const cwd = resolve(fileURLToPath(new URL(".", import.meta.url)));

    const result = await new CodexProviderAdapter({ executable: process.execPath, args: ["-e", script] }).run({
      task_id: "task_demo",
      candidate_id: "candidate_demo",
      prompt: "demo",
      cwd
    });

    expect(result.worker.evidence.native).toMatchObject({ pwd: cwd, cwd });
    expect(result.process.exit_code).toBe(0);
  });

  test("normalizes Codex JSONL result envelopes", () => {
    const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: [
        JSON.stringify({ type: "started" }),
        JSON.stringify({
          type: "result",
          result: JSON.stringify({ status: "completed", summary: "codex envelope done", changed_files: ["c.ts"], evidence: { command: "codex" } })
        })
      ].join("\n"),
      stderr: ""
    });

    expect(result.worker.summary).toBe("codex envelope done");
    expect(result.worker.changed_files).toEqual(["c.ts"]);
    expect(result.process.stdout).toContain('"type":"started"');
  });

  test("prefers Codex agent_message worker result over telemetry envelopes", () => {
    const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: [
        JSON.stringify({ type: "thread.started", thread_id: "thread_demo" }),
        JSON.stringify({
          type: "item.completed",
          item: {
            type: "agent_message",
            text: JSON.stringify({
              schema: "runway.worker_result.v1",
              task_id: "task_demo",
              candidate_id: "candidate_demo",
              status: "success",
              summary: "codex made the claimed edit",
              changed_files: ["live-provider.txt"],
              evidence: { command: "codex" }
            })
          }
        }),
        JSON.stringify({ type: "turn.completed", usage: { input_tokens: 1 } })
      ].join("\n"),
      stderr: ""
    });

    expect(result.worker.summary).toBe("codex made the claimed edit");
    expect(result.worker.changed_files).toEqual(["live-provider.txt"]);
    expect(result.worker.evidence.native).toMatchObject({ command: "codex" });
  });

  test("preserves provider supplied failure_class", () => {
    const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: JSON.stringify({
        status: "failed",
        failure_class: "verification_failed",
        summary: "provider saw verification fail",
        changed_files: ["README.md"],
        evidence: { command: "codex" }
      }),
      stderr: "stderr evidence"
    });

    expect(result.worker.status).toBe("failed");
    expect(result.worker.failure_class).toBe("verification_failed");
    expect(result.worker.summary).toBe("provider saw verification fail");
    expect(result.process.stderr).toBe("stderr evidence");
  });

  test("rejects truly unknown worker status as malformed_result", () => {
    const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: JSON.stringify({ status: "quantum_superposition", summary: "ambiguous", changed_files: [], evidence: {} }),
      stderr: ""
    });

    expect(result.worker.status).toBe("failed");
    expect(result.worker.failure_class).toBe("malformed_result");
    expect(result.process.exit_code).toBe(0);
  });

  test("classifies crashes", () => {
    const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", { exitCode: 2, stdout: "raw out", stderr: "boom" });

    expect(result.worker.failure_class).toBe("adapter_crashed");
    expect(result.process).toMatchObject({
      stdout: "raw out",
      stderr: "boom",
      exit_code: 2,
      timed_out: false
    });
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
    expect(result.worker.status).toBe("failed");
    expect(result.worker.failure_class).toBe("adapter_crashed");
    expect(result.process).toMatchObject({
      stdout: "",
      exit_code: null,
      timed_out: false
    });
    expect(result.process.stderr).toContain("failed to start");
  });

  test("preserves timeout process evidence", async () => {
    const script = `
      process.stdout.write("before timeout");
      setTimeout(() => process.stdout.write("after timeout"), 1000);
    `;

    const result = await new CodexProviderAdapter({ executable: process.execPath, args: ["-e", script], timeout_ms: 200 }).run({
      task_id: "task_demo",
      candidate_id: "candidate_demo",
      prompt: "demo"
    });

    expect(result.worker.status).toBe("failed");
    expect(result.worker.failure_class).toBe("timeout");
    expect(result.process.stdout).toContain("before timeout");
    expect(result.process.timed_out).toBe(true);
    expect(result.process.completed_at).toMatch(/\d{4}-\d{2}-\d{2}T/);
  });

  test("recognizes absolute Codex CLI executable paths", () => {
    const args = providerProcessArgs(
      "codex",
      {
        executable: "/usr/local/bin/codex",
        args: ["exec", "--json", "-"],
        model: "gpt-5.5",
        effort: "high"
      },
      "/tmp/work",
      { task_id: "t", candidate_id: "c", prompt: "p" }
    );
    expect(args).toContain("--model");
    expect(args).toContain("gpt-5.5");
    expect(args).toContain("--reasoning");
    expect(args).toContain("high");
    expect(args).toContain("--cd");
    expect(args).toContain("/tmp/work");
  });
});
