import { describe, expect, test } from "bun:test";
import { PROFILE_PRESETS, parseCli, resolveCliProfile } from "../src/index";

describe("CLI --profile preset", () => {
  test("max-quality applies opus/opus across main and subagent", () => {
    const profile = resolveCliProfile(parseCli(["run", "--provider", "claude", "--profile", "max-quality"]));
    expect(profile).toMatchObject({
      provider: "claude",
      main_model: "opus",
      main_reasoning: "high",
      subagent_model: "opus",
      subagent_reasoning: "high"
    });
  });

  test("balanced applies opus main + sonnet subagent (kws-CME-aligned default)", () => {
    const profile = resolveCliProfile(parseCli(["run", "--provider", "claude", "--profile", "balanced"]));
    expect(profile).toMatchObject({
      main_model: "opus",
      main_reasoning: "high",
      subagent_model: "sonnet",
      subagent_reasoning: "medium"
    });
  });

  test("cost-saver applies haiku main + sonnet subagent", () => {
    const profile = resolveCliProfile(parseCli(["run", "--provider", "claude", "--profile", "cost-saver"]));
    expect(profile).toMatchObject({
      main_model: "haiku",
      main_reasoning: "medium",
      subagent_model: "sonnet",
      subagent_reasoning: "medium"
    });
  });

  test("individual --main-model / --subagent-reasoning flags override the preset", () => {
    const profile = resolveCliProfile(parseCli([
      "run",
      "--provider", "claude",
      "--profile", "balanced",
      "--subagent-model", "haiku",
      "--subagent-reasoning", "high"
    ]));
    expect(profile.subagent_model).toBe("haiku");
    expect(profile.subagent_reasoning).toBe("high");
    expect(profile.main_model).toBe("opus");
  });

  test("rejects unknown preset values", () => {
    expect(() => resolveCliProfile(parseCli(["run", "--profile", "ultimate"])))
      .toThrow(/unknown --profile preset/);
  });

  test("run --help surfaces the preset + model flags", async () => {
    const { runCli } = await import("../src/index");
    const help = await runCli(["run", "--help"]) as { usage: string };
    expect(help.usage).toContain("--profile");
    expect(help.usage).toContain("max-quality");
    expect(help.usage).toContain("--main-model");
    expect(help.usage).toContain("--subagent-model");
    expect(help.usage).toContain("--run <id>");
  });

  test("PROFILE_PRESETS table is exported for downstream tooling", () => {
    expect(Object.keys(PROFILE_PRESETS).sort()).toEqual(["balanced", "cost-saver", "max-quality"]);
  });
});
