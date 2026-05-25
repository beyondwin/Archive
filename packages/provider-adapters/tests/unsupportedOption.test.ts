import { describe, expect, test } from "bun:test";
import { gatherUnsupportedOptionWarnings } from "../src/processAdapters";

describe("unsupported provider option warnings (C4)", () => {
  test("claude returns no warnings for supported options", () => {
    const warnings = gatherUnsupportedOptionWarnings("claude", {
      executable: "claude",
      settings_path: "/x/settings.json",
      mcp_config_path: "/x/mcp.json",
      session_id: "00000000-0000-0000-0000-000000000000",
      effort: "high"
    });
    expect(warnings).toEqual([]);
  });

  test("codex emits a warning for every option the adapter cannot honor", () => {
    const warnings = gatherUnsupportedOptionWarnings("codex", {
      executable: "codex",
      settings_path: "/x/settings.json",
      mcp_config_path: "/x/mcp.json",
      session_id: "explicit-session",
      effort: "high"
    });
    expect(warnings).toContain("unsupported_provider_option: settings_path (codex)");
    expect(warnings).toContain("unsupported_provider_option: mcp_config_path (codex)");
    expect(warnings).toContain("unsupported_provider_option: session_id_first_attempt (codex)");
    expect(warnings).toContain("unsupported_provider_option: reasoning (codex)");
  });

  test("session_id_first_attempt is NOT warned when resume_session_id is also set", () => {
    const warnings = gatherUnsupportedOptionWarnings("codex", {
      executable: "codex",
      session_id: "session-x",
      resume_session_id: "session-x"
    });
    expect(warnings).not.toContain("unsupported_provider_option: session_id_first_attempt (codex)");
  });

  test("codex emits no warnings when only the supported subset is configured", () => {
    const warnings = gatherUnsupportedOptionWarnings("codex", {
      executable: "codex",
      args: ["exec", "--json", "-"],
      model: "gpt-5.5"
    });
    expect(warnings).toEqual([]);
  });
});
