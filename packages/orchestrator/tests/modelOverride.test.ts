import { describe, expect, test } from "bun:test";
import { resolveExecutionProfile, resolveProviderProcesses } from "../src";

describe("model override precedence", () => {
  test("natural-language override can win when passed first", () => {
    const profile = resolveExecutionProfile({ provider: "claude", main_reasoning: "high" }, { provider: "codex", main_reasoning: "xhigh" });
    expect(profile.provider).toBe("claude");
    expect(profile.main.reasoning).toBe("high");
  });

  test("default claude profile wires opus + high into provider processes", () => {
    const profile = resolveExecutionProfile({ provider: "claude" });
    const processes = resolveProviderProcesses(profile, undefined);
    expect(processes.claude).toMatchObject({
      executable: "claude",
      model: "opus",
      effort: "high"
    });
  });

  test("user-provided claude options override the profile defaults", () => {
    const profile = resolveExecutionProfile({ provider: "claude", subagent_model: "sonnet" });
    const processes = resolveProviderProcesses(profile, {
      claude: { executable: "claude", model: "haiku" }
    });
    expect(processes.claude?.model).toBe("haiku");
  });

  test("fake provider produces no claude entry", () => {
    const profile = resolveExecutionProfile({ provider: "fake" });
    const processes = resolveProviderProcesses(profile, undefined);
    expect(processes.claude).toBeUndefined();
  });
});
