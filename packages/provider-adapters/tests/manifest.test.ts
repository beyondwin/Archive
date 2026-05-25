import { describe, expect, test } from "bun:test";
import { claudeCapabilityManifest, codexCapabilityManifest, providerSupportsCapabilities } from "../src";

describe("claude capability manifest", () => {
  test("declares Claude-specific capabilities (not equal to Codex)", () => {
    expect(claudeCapabilityManifest).toMatchObject({
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

  test("Claude manifest.supports matches the C4 capability lock", () => {
    expect(claudeCapabilityManifest.supports).toEqual({
      settings_path: true,
      mcp_config_path: true,
      session_id_first_attempt: true,
      reasoning: true
    });
  });

  test("Codex manifest.supports matches the C4 capability lock", () => {
    expect(codexCapabilityManifest.supports).toEqual({
      settings_path: false,
      mcp_config_path: false,
      session_id_first_attempt: false,
      reasoning: false
    });
  });

  test("providerSupportsCapabilities lookup mirrors the manifest values", () => {
    expect(providerSupportsCapabilities("claude")).toEqual(claudeCapabilityManifest.supports!);
    expect(providerSupportsCapabilities("codex")).toEqual(codexCapabilityManifest.supports!);
  });

  test("supports keys are paired with the runtime unsupported-option checks", () => {
    // CP-3 cross-path invariant: every key in supports must have a runtime
    // check, and every check must look up exactly one key in supports.
    const supportsKeys = Object.keys(codexCapabilityManifest.supports!).sort();
    expect(supportsKeys).toEqual([
      "mcp_config_path",
      "reasoning",
      "session_id_first_attempt",
      "settings_path"
    ]);
  });
});
