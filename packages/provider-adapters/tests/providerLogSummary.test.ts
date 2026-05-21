import { describe, expect, test } from "bun:test";
import { summarizeProviderStderr } from "../src/logSummary";

describe("provider log summary", () => {
  test("groups repeated provider stderr noise into stable categories", () => {
    const summary = summarizeProviderStderr([
      "ERROR codex_core::session: failed to load skill /bad/SKILL.md",
      "WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt",
      "WARN codex_core_skills::loader: ignoring interface.icon_small",
      "WARN codex_mcp::rmcp_client: failed to initialize MCP client during shutdown",
      "WARN something else",
      "plain line"
    ].join("\n"));

    expect(summary.total_lines).toBe(6);
    expect(summary.counts).toMatchObject({
      error: 1,
      warning: 1,
      mcp: 1,
      plugin_manifest: 1,
      skill_loader: 1,
      other: 1
    });
    expect(summary.samples.map((sample) => sample.category)).toEqual(
      expect.arrayContaining(["error", "plugin_manifest", "skill_loader", "mcp"])
    );
  });
});
