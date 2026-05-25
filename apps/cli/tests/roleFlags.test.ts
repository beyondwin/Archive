import { describe, expect, test } from "bun:test";
import { parseCli, parseRoleModelFlag, parseRoleReasoningFlag, resolveCliProfile } from "../src/index";

describe("CLI --role-model / --role-reasoning (D2)", () => {
  test("parses --role-model into a per-role map", () => {
    const profile = resolveCliProfile(parseCli([
      "run",
      "--provider", "claude",
      "--role-model", "implement=opus,review=sonnet-4-6,verify_assist=haiku-4-5"
    ]));
    expect(profile.role_models).toEqual({
      implement: "opus",
      review: "sonnet-4-6",
      verify_assist: "haiku-4-5"
    });
  });

  test("parses --role-reasoning with validated levels", () => {
    const profile = resolveCliProfile(parseCli([
      "run",
      "--provider", "claude",
      "--role-reasoning", "implement=high,review=medium"
    ]));
    expect(profile.role_reasoning).toEqual({ implement: "high", review: "medium" });
  });

  test("rejects unknown role key", () => {
    expect(() => parseRoleModelFlag("planner=opus"))
      .toThrow(/unknown role 'planner'/);
  });

  test("rejects unknown reasoning level", () => {
    expect(() => parseRoleReasoningFlag("implement=insane"))
      .toThrow(/unknown level 'insane'/);
  });

  test("partial --role-model set is OK (others inherit profile default)", () => {
    const profile = resolveCliProfile(parseCli([
      "run",
      "--provider", "claude",
      "--profile", "balanced",
      "--role-model", "review=haiku"
    ]));
    expect(profile.role_models?.review).toBe("haiku");
    // implement inherits from the balanced preset override (opus)
    expect(profile.role_models?.implement).toBe("opus");
  });

  test("--role-model composes with --subagent-model without conflict", () => {
    const profile = resolveCliProfile(parseCli([
      "run",
      "--provider", "claude",
      "--subagent-model", "sonnet",
      "--role-model", "verify_assist=haiku"
    ]));
    expect(profile.subagent_model).toBe("sonnet");
    expect(profile.role_models?.verify_assist).toBe("haiku");
  });

  test("help surfaces the role-aware flags", async () => {
    const { runCli } = await import("../src/index");
    const help = await runCli(["run", "--help"]) as { usage: string };
    expect(help.usage).toContain("--role-model");
    expect(help.usage).toContain("--role-reasoning");
  });
});
