import { describe, expect, test } from "bun:test";
import { FakeProviderAdapter } from "../src";

describe("fake provider", () => {
  test("returns deterministic worker result", async () => {
    const result = await new FakeProviderAdapter().run({ task_id: "task_demo", candidate_id: "candidate_demo", prompt: "demo" });
    expect(result.worker.status).toBe("completed");
    expect(result.worker.evidence.provider).toBe("fake-provider");
    expect(result.process).toMatchObject({
      stdout: "",
      stderr: "",
      exit_code: 0,
      timed_out: false,
      event_stream: null
    });
  });

  test("describes the offline boundary without direct AgentLens writes", () => {
    expect(new FakeProviderAdapter().describe()).toEqual({
      provider: "fake",
      execution: "deterministic",
      direct_agentlens_writes: false
    });
  });
});
