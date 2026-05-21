import { describe, expect, test } from "bun:test";
import { buildProviderPrompt } from "../src/processAdapters";

describe("provider role prompts", () => {
  test("includes task packet contract and forbids direct apply or AgentLens writes", () => {
    const prompt = buildProviderPrompt("codex", {
      task_id: "task_a",
      candidate_id: "candidate_task_a",
      role: "implement",
      prompt: "Task body",
      task_packet_path: "/tmp/task_packet.json"
    });

    expect(prompt).toContain("role: implement");
    expect(prompt).toContain("task_packet_path: /tmp/task_packet.json");
    expect(prompt).toContain("Do not write AgentLens events directly.");
    expect(prompt).toContain("Do not apply changes to the source checkout.");
  });
});
