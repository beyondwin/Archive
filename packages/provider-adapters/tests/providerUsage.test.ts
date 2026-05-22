import { describe, expect, test } from "bun:test";
import { normalizeProcessOutput } from "../src/processAdapters";

describe("provider usage extraction", () => {
  test("extracts usage and actual model from worker evidence", () => {
    const result = normalizeProcessOutput("codex", "task_a", "candidate_task_a", {
      exitCode: 0,
      stdout: JSON.stringify({
        schema: "runway.worker_result.v1",
        task_id: "task_a",
        candidate_id: "candidate_task_a",
        status: "completed",
        changed_files: [],
        summary: "ok",
        evidence: {
          actual_model: { model: "gpt-5.5", reasoning: "high", source: "provider_json" },
          usage: { input_tokens: 10, output_tokens: 3, cached_read_tokens: 2, cached_write_tokens: 0 },
          usage_source: "provider_json"
        }
      }),
      stderr: ""
    });

    expect(result.metadata?.actual_model?.model).toBe("gpt-5.5");
    expect(result.metadata?.usage?.input_tokens).toBe(10);
    expect(result.metadata?.usage_source).toBe("provider_json");
  });
});
