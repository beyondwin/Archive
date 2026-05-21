import { describe, expect, test } from "bun:test";
import { resolveExecutionProfile } from "../src";

describe("execution profile resolver", () => {
  test("defaults to Codex multi-agent profile", () => {
    const profile = resolveExecutionProfile();
    expect(profile.execution_mode).toBe("multi-agent");
    expect(profile.main).toEqual({ model: "gpt-5.5", reasoning: "xhigh" });
    expect(profile.subagent).toEqual({ model: "gpt-5.5", reasoning: "high" });
  });

  test("supports Claude override", () => {
    expect(resolveExecutionProfile({ provider: "claude" }).main).toEqual({ model: "opus", reasoning: "high" });
  });
});
