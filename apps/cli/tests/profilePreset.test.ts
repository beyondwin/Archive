import { describe, expect, test } from "bun:test";
import { PROFILE_PRESETS, parseCli, resolveCliProfile, resolveCliRunDefaults } from "../src/index";

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

  test("max-quality applies Codex-native GPT-5.5 routing for Codex provider", () => {
    const profile = resolveCliProfile(parseCli(["run", "--provider", "codex", "--profile", "max-quality"]));
    expect(profile).toMatchObject({
      provider: "codex",
      main_model: "gpt-5.5",
      main_reasoning: "xhigh",
      subagent_model: "gpt-5.5",
      subagent_reasoning: "high",
      role_models: {
        implement: "gpt-5.5",
        review: "gpt-5.5",
        verify_assist: "gpt-5.5",
        repair: "gpt-5.5"
      },
      role_reasoning: {
        implement: "high",
        review: "high",
        verify_assist: "high",
        repair: "high"
      }
    });
  });

  test("Codex max-quality turns on the strongest runtime harness defaults", () => {
    const parsed = parseCli(["run", "--provider", "codex", "--profile", "max-quality"]);
    const profile = resolveCliProfile(parsed);

    expect(resolveCliRunDefaults(parsed, profile)).toEqual({
      plan_preflight: "full",
      spec_slice: "manifest",
      hook_config: "builtin",
      require_method_evidence: true
    });
  });

  test("explicit run harness flags override Codex max-quality defaults", () => {
    const parsed = parseCli([
      "run",
      "--provider", "codex",
      "--profile", "max-quality",
      "--plan-preflight", "off",
      "--spec-slice", "off",
      "--hook-config", "off"
    ]);
    const profile = resolveCliProfile(parsed);

    expect(resolveCliRunDefaults(parsed, profile)).toEqual({
      plan_preflight: "off",
      spec_slice: "off",
      hook_config: "off",
      require_method_evidence: true
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
