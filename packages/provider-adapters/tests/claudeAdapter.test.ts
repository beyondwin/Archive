import { describe, expect, test } from "bun:test";
import {
  ClaudeProviderAdapter,
  buildProviderSystemPrompt,
  buildProviderUserPrompt,
  buildRetryPromptPrefix,
  normalizeProcessOutput,
  providerProcessArgs,
  providerProcessArgsWithWarnings
} from "../src";

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

  test("role 'implement' uses acceptEdits permission mode", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "claude", args: ["-p"] },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p", role: "implement" }
    );
    expect(args).toContain("--permission-mode");
    const permIdx = args.indexOf("--permission-mode");
    expect(args[permIdx + 1]).toBe("acceptEdits");
    expect(args).not.toContain("--disallowedTools");
    expect(args).not.toContain("--allowedTools");
  });

  test("role 'fix' uses implement defaults", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "claude", args: ["-p"] },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p", role: "fix" }
    );
    const permIdx = args.indexOf("--permission-mode");
    expect(args[permIdx + 1]).toBe("acceptEdits");
  });

  test("role 'review' switches to plan mode and disables edit tools", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "claude", args: ["-p"] },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p", role: "review" }
    );
    const permIdx = args.indexOf("--permission-mode");
    expect(args[permIdx + 1]).toBe("plan");
    expect(args).toContain("--disallowedTools");
    const disallowIdx = args.indexOf("--disallowedTools");
    expect(args[disallowIdx + 1]).toBe("Edit,Write,MultiEdit");
  });

  test("role 'verify_assist' uses acceptEdits with allowedTools whitelist", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "claude", args: ["-p"] },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p", role: "verify_assist" }
    );
    const permIdx = args.indexOf("--permission-mode");
    expect(args[permIdx + 1]).toBe("acceptEdits");
    expect(args).toContain("--allowedTools");
    const allowIdx = args.indexOf("--allowedTools");
    expect(args[allowIdx + 1]).toBe("Bash,Read,Glob,Grep");
  });

  test("unknown role falls back to implement and emits a warning", () => {
    const { args, warnings } = providerProcessArgsWithWarnings(
      "claude",
      { executable: "claude", args: ["-p"] },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p", role: "wat" as unknown as "implement" }
    );
    const permIdx = args.indexOf("--permission-mode");
    expect(args[permIdx + 1]).toBe("acceptEdits");
    expect(warnings.join("\n")).toMatch(/unknown provider role/);
  });

  test("undefined role does not emit a warning", () => {
    const { warnings } = providerProcessArgsWithWarnings(
      "claude",
      { executable: "claude", args: ["-p"] },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p" }
    );
    expect(warnings).toEqual([]);
  });

  test("--append-system-prompt is injected with the role-specific system prompt", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "claude", args: ["-p"] },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p", role: "implement" }
    );
    const idx = args.indexOf("--append-system-prompt");
    expect(idx).toBeGreaterThan(-1);
    expect(args[idx + 1]).toBe(buildProviderSystemPrompt("implement"));
  });

  test("buildProviderSystemPrompt returns byte-stable content per role", () => {
    const implement = buildProviderSystemPrompt("implement");
    const review = buildProviderSystemPrompt("review");
    expect(implement).toBe(buildProviderSystemPrompt("implement"));
    expect(implement).not.toBe(review);
    expect(implement).toContain("role: implement");
    expect(review).toContain("role: review");
    expect(implement).toContain("Required JSON fields");
    expect(implement).toContain("Do not write AgentLens events directly.");
  });

  test("buildProviderUserPrompt omits role / contract reminder block", () => {
    const userPrompt = buildProviderUserPrompt("claude", {
      task_id: "task_demo",
      candidate_id: "candidate_demo",
      role: "implement",
      prompt: "Task body."
    });
    expect(userPrompt).toContain("task_id: task_demo");
    expect(userPrompt).toContain("Task body.");
    expect(userPrompt).not.toContain("Do not write AgentLens events directly.");
    expect(userPrompt).not.toContain("Required JSON fields");
  });

  test("retry_context prepends a retry prefix into the user prompt", () => {
    const userPrompt = buildProviderUserPrompt("claude", {
      task_id: "task_retry",
      candidate_id: "candidate_task_retry",
      role: "implement",
      prompt: "Task body.",
      retry_context: { failure_class: "verification_failed", stderr_summary: "compile error" }
    });
    expect(userPrompt.startsWith("Prior attempt failed: verification_failed.")).toBe(true);
    expect(userPrompt).toContain("stderr summary: compile error");
    expect(userPrompt).toContain("runway.worker_result.v1");
    expect(userPrompt).toContain("Task body.");
  });

  test("buildRetryPromptPrefix truncates long stderr summaries to 300 chars", () => {
    const longSummary = "x".repeat(500);
    const prefix = buildRetryPromptPrefix({ failure_class: "adapter_crashed", stderr_summary: longSummary });
    expect(prefix).toContain("Prior attempt failed: adapter_crashed.");
    expect(prefix).toContain("x".repeat(300));
    expect(prefix).not.toContain("x".repeat(301));
  });

  test("passes --settings and --mcp-config when provided", () => {
    const args = providerProcessArgs(
      "claude",
      {
        executable: "claude",
        args: ["-p"],
        settings_path: "/etc/waygent/claude-settings.json",
        mcp_config_path: "/etc/waygent/mcp.json"
      },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p" }
    );
    expect(args).toContain("--settings");
    const settingsIdx = args.indexOf("--settings");
    expect(args[settingsIdx + 1]).toBe("/etc/waygent/claude-settings.json");
    expect(args).toContain("--mcp-config");
    const mcpIdx = args.indexOf("--mcp-config");
    expect(args[mcpIdx + 1]).toBe("/etc/waygent/mcp.json");
  });

  test("session_id flows through as --session-id on first attempt", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "claude", args: ["-p"], session_id: "session_x" },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p" }
    );
    expect(args).toContain("--session-id");
    const idx = args.indexOf("--session-id");
    expect(args[idx + 1]).toBe("session_x");
    expect(args).not.toContain("--resume");
  });

  test("resume_session_id flows through as --resume and omits --session-id", () => {
    const args = providerProcessArgs(
      "claude",
      { executable: "claude", args: ["-p"], session_id: "session_x", resume_session_id: "session_x" },
      undefined,
      { task_id: "t", candidate_id: "c", prompt: "p" }
    );
    expect(args).toContain("--resume");
    const idx = args.indexOf("--resume");
    expect(args[idx + 1]).toBe("session_x");
    expect(args).not.toContain("--session-id");
  });

  test("detects resume_session_missing from stderr signal even on adapter crash", () => {
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", {
      exitCode: 1,
      stdout: "",
      stderr: "Error: session not found: session_x",
      timedOut: false
    });
    expect(result.worker.failure_class).toBe("adapter_crashed");
    expect(result.metadata?.resume_session_missing).toBe(true);
  });
});
