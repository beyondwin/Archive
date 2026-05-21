import { describe, expect, test } from "bun:test";
import { FakeProviderAdapter } from "../src";

describe("fake provider", () => {
  test("returns deterministic worker result", async () => {
    const result = await new FakeProviderAdapter().run({ task_id: "task_demo", candidate_id: "candidate_demo", prompt: "demo" });
    expect(result.status).toBe("completed");
    expect(result.evidence.provider).toBe("fake-provider");
  });
});
