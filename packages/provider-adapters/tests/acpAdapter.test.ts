import { describe, expect, test } from "bun:test";
import { acpCapabilityManifest, normalizeProcessOutput } from "../src";

describe("ACP adapter boundary", () => {
  test("keeps ACP events behind worker-result contract", () => {
    const result = normalizeProcessOutput("acp", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: JSON.stringify({ summary: "acp done", evidence: { transcript_artifact: "artifacts/transcript.json" } }),
      stderr: ""
    });
    expect(result.worker.schema).toBe("runway.worker_result.v1");
    expect(acpCapabilityManifest.file_edits).toBe(false);
  });
});
