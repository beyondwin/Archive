import { describe, expect, test } from "bun:test";
import { claudeCapabilityManifest, codexCapabilityManifest } from "../src";

describe("claude capability manifest", () => {
  test("declares Claude-specific capabilities (not equal to Codex)", () => {
    expect(claudeCapabilityManifest).toEqual({
      schema: "provider.capability_manifest.v1",
      provider: "claude",
      supported_modes: ["single-agent", "multi-agent", "review", "verify"],
      tool_calls: true,
      file_edits: true,
      shell: true,
      streaming: true,
      approvals: false,
      result_schema: "runway.worker_result.v1"
    });
    expect(claudeCapabilityManifest.provider).toBe("claude");
    expect(claudeCapabilityManifest).not.toEqual(codexCapabilityManifest);
    expect(claudeCapabilityManifest.approvals).toBe(false);
    expect(codexCapabilityManifest.approvals).toBe(true);
  });
});
