import { describe, expect, test } from "bun:test";
import { resolveExecutionProfile } from "../src";

describe("model override precedence", () => {
  test("natural-language override can win when passed first", () => {
    const profile = resolveExecutionProfile({ provider: "claude", main_reasoning: "high" }, { provider: "codex", main_reasoning: "xhigh" });
    expect(profile.provider).toBe("claude");
    expect(profile.main.reasoning).toBe("high");
  });
});
