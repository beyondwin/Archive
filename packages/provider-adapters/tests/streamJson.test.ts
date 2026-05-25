import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { normalizeProcessOutput } from "../src/processAdapters";

const fixturePath = join(import.meta.dir, "fixtures", "claude", "stream_json_success.jsonl");

describe("claude stream-json parsing", () => {
  test("extracts worker_result from final result event in a JSONL stream", () => {
    const stdout = readFileSync(fixturePath, "utf8");
    const result = normalizeProcessOutput("claude", "task_stream", "candidate_task_stream", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false,
      eventStream: stdout
    });
    expect(result.worker.status).toBe("completed");
    expect(result.worker.summary).toBe("stream-json fixture worker_result");
    expect(result.worker.changed_files).toEqual(["src/feature.ts"]);
    expect(result.process.event_stream).toBe(stdout);
  });

  test("attests model from system.init event in the stream", () => {
    const stdout = readFileSync(fixturePath, "utf8");
    const result = normalizeProcessOutput("claude", "task_stream", "candidate_task_stream", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false,
      eventStream: stdout
    });
    expect(result.metadata?.actual_model.model).toBe("claude-opus-4-7");
    expect(result.metadata?.actual_model.source).toBe("provider_json");
  });

  test("captures usage including cache fields from the result event", () => {
    const stdout = readFileSync(fixturePath, "utf8");
    const result = normalizeProcessOutput("claude", "task_stream", "candidate_task_stream", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false,
      eventStream: stdout
    });
    expect(result.metadata?.usage).toEqual({
      input_tokens: 1500,
      output_tokens: 420,
      cached_read_tokens: 900,
      cached_write_tokens: 200
    });
    expect(result.metadata?.usage_source).toBe("provider_json");
  });

  test("captures session_id from system.init for resume evidence", () => {
    const stdout = readFileSync(fixturePath, "utf8");
    const result = normalizeProcessOutput("claude", "task_stream", "candidate_task_stream", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false,
      eventStream: stdout
    });
    expect(result.metadata?.session_id).toBe("session_stream_fixture");
  });
});
