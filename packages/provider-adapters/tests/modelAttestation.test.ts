import { describe, expect, test } from "bun:test";
import { FakeProviderAdapter } from "../src/fakeProvider";
import { normalizeProcessOutput } from "../src/processAdapters";

describe("model attestation extraction", () => {
  test("fake provider attests the fake model", async () => {
    const result = await new FakeProviderAdapter().run({
      task_id: "task_a",
      candidate_id: "candidate_task_a",
      prompt: "demo"
    });

    expect(result.metadata?.actual_model).toEqual({ model: "fake", reasoning: null, source: "fake_provider" });
  });

  test("missing provider model is recorded as unknown", () => {
    const result = normalizeProcessOutput("claude", "task_a", "candidate_task_a", {
      exitCode: 0,
      stdout: JSON.stringify({ status: "completed", changed_files: [], summary: "ok", evidence: {} }),
      stderr: ""
    });

    expect(result.metadata?.actual_model).toEqual({ model: null, reasoning: null, source: "unknown" });
  });
});
