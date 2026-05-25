import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { normalizeProcessOutput } from "../src/processAdapters";
import type { ToolCallEvidence } from "../src/types";

const fixturePath = join(import.meta.dir, "fixtures", "claude", "stream_json_with_tools.jsonl");

describe("Claude stream-json tool-use audit (D1)", () => {
  test("captures tool_calls in evidence with pairing, sizes, and duration", () => {
    const stdout = readFileSync(fixturePath, "utf8");
    const result = normalizeProcessOutput("claude", "task_tools", "candidate_task_tools", {
      exitCode: 0,
      stdout,
      stderr: "",
      eventStream: stdout
    });
    const calls = result.worker.evidence.tool_calls as ToolCallEvidence[] | undefined;
    expect(Array.isArray(calls)).toBe(true);
    expect(calls!.length).toBe(2);
    const read = calls!.find((call) => call.name === "Read");
    expect(read).toBeDefined();
    expect(read!.tool_use_id).toBe("tool_1");
    expect(read!.input_summary.keys).toEqual(["file_path", "limit"]);
    expect(read!.input_summary.sizes_bytes.file_path).toBe(Buffer.byteLength("/work/src/feature.ts", "utf8"));
    expect(read!.input_summary.sizes_bytes.limit).toBeUndefined();
    expect(read!.result).not.toBeNull();
    expect(read!.result!.status).toBe("ok");
    expect(read!.result!.is_error).toBe(false);
    expect(read!.result!.summary_bytes).toBe(Buffer.byteLength("file contents abc", "utf8"));
    expect(read!.duration_ms).toBe(250);

    const bash = calls!.find((call) => call.name === "Bash");
    expect(bash).toBeDefined();
    expect(bash!.tool_use_id).toBe("tool_2");
    expect(bash!.input_summary.keys).toEqual(["command", "description"]);
    expect(bash!.result!.status).toBe("error");
    expect(bash!.result!.is_error).toBe(true);
    expect(bash!.result!.summary_bytes).toBe(Buffer.byteLength("FAIL: 1 test\n", "utf8"));
    expect(bash!.duration_ms).toBe(500);
  });

  test("never stores raw input values or tool_result content body", () => {
    const stdout = readFileSync(fixturePath, "utf8");
    const result = normalizeProcessOutput("claude", "task_tools", "candidate_task_tools", {
      exitCode: 0,
      stdout,
      stderr: "",
      eventStream: stdout
    });
    const serialized = JSON.stringify(result.worker.evidence.tool_calls);
    expect(serialized).not.toContain("/work/src/feature.ts");
    expect(serialized).not.toContain("bun test");
    expect(serialized).not.toContain("file contents abc");
    expect(serialized).not.toContain("FAIL: 1 test");
  });

  test("returns an empty array when stream-json has no tool calls", () => {
    const baseFixture = join(import.meta.dir, "fixtures", "claude", "stream_json_success.jsonl");
    const stdout = readFileSync(baseFixture, "utf8");
    const result = normalizeProcessOutput("claude", "task_a", "candidate_a", {
      exitCode: 0,
      stdout,
      stderr: "",
      eventStream: stdout
    });
    expect(result.worker.evidence.tool_calls).toEqual([]);
  });

  test("yields result=null for tool_use without matching tool_result (worker aborted)", () => {
    const stdout = [
      JSON.stringify({ type: "system", subtype: "init", session_id: "s", model: "claude-opus-4-7" }),
      JSON.stringify({ type: "assistant", message: { role: "assistant", content: [{ type: "tool_use", id: "stuck_1", name: "Read", input: { path: "/x" } }] } }),
      JSON.stringify({ type: "result", subtype: "success", is_error: false, result: '{"schema":"runway.worker_result.v1","task_id":"task_abort","candidate_id":"cand_abort","status":"completed","changed_files":[],"summary":"abort","evidence":{}}' })
    ].join("\n");
    const result = normalizeProcessOutput("claude", "task_abort", "cand_abort", {
      exitCode: 0,
      stdout,
      stderr: "",
      eventStream: stdout
    });
    const calls = result.worker.evidence.tool_calls as ToolCallEvidence[];
    expect(calls.length).toBe(1);
    expect(calls[0]!.result).toBeNull();
    expect(calls[0]!.duration_ms).toBeNull();
  });

  test("tool_calls key absent when stream-json is not the format (codex path)", () => {
    const stdout = JSON.stringify({
      schema: "runway.worker_result.v1",
      task_id: "task_no_stream",
      candidate_id: "cand_no_stream",
      status: "completed",
      changed_files: [],
      summary: "no stream",
      evidence: {}
    });
    const result = normalizeProcessOutput("codex", "task_no_stream", "cand_no_stream", {
      exitCode: 0,
      stdout,
      stderr: ""
    });
    expect(result.worker.evidence.tool_calls).toBeUndefined();
  });
});
