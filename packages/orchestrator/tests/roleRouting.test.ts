import { describe, expect, test } from "bun:test";
import { applyRoleRoutingToProcesses, resolveExecutionProfile, resolveProviderProcesses } from "../src";

describe("role-aware model routing (D2)", () => {
  test("default profile populates roles { implement, review, verify_assist }", () => {
    const profile = resolveExecutionProfile({ provider: "claude" });
    expect(profile.roles.implement).toBeDefined();
    expect(profile.roles.review).toBeDefined();
    expect(profile.roles.verify_assist).toBeDefined();
  });

  test("--subagent-model fills all roles that --role-model does not specify", () => {
    const profile = resolveExecutionProfile({
      provider: "claude",
      subagent_model: "sonnet",
      subagent_reasoning: "medium",
      role_models: { implement: "opus" },
      role_reasoning: { implement: "high" }
    });
    expect(profile.roles.implement).toEqual({ model: "opus", reasoning: "high" });
    expect(profile.roles.review).toEqual({ model: "sonnet", reasoning: "medium" });
    expect(profile.roles.verify_assist).toEqual({ model: "sonnet", reasoning: "medium" });
  });

  test("priority matrix: --role-model beats --subagent-model beats profile default", () => {
    const profile = resolveExecutionProfile({
      provider: "claude",
      subagent_model: "sonnet",
      role_models: { review: "haiku" }
    });
    // review role gets the explicit --role-model override
    expect(profile.roles.review.model).toBe("haiku");
    // implement role falls through to --subagent-model
    expect(profile.roles.implement.model).toBe("sonnet");
  });

  test("--main-model only affects main coordinator, not worker roles", () => {
    const profile = resolveExecutionProfile({
      provider: "claude",
      main_model: "opus",
      main_reasoning: "high",
      subagent_model: "sonnet"
    });
    expect(profile.main.model).toBe("opus");
    expect(profile.roles.implement.model).toBe("sonnet");
    expect(profile.roles.review.model).toBe("sonnet");
  });

  test("applyRoleRoutingToProcesses overrides model/effort per role at dispatch time", () => {
    const profile = resolveExecutionProfile({
      provider: "claude",
      subagent_model: "sonnet",
      role_models: { implement: "opus", review: "haiku" },
      role_reasoning: { implement: "high", review: "medium" }
    });
    const base = resolveProviderProcesses(profile, undefined);
    const implOverlay = applyRoleRoutingToProcesses(base, profile, "implement");
    expect(implOverlay.claude?.model).toBe("opus");
    expect(implOverlay.claude?.effort).toBe("high");
    const reviewOverlay = applyRoleRoutingToProcesses(base, profile, "review");
    expect(reviewOverlay.claude?.model).toBe("haiku");
    expect(reviewOverlay.claude?.effort).toBe("medium");
  });

  test("applyRoleRoutingToProcesses is a no-op in single-agent mode", () => {
    const profile = resolveExecutionProfile({
      provider: "claude",
      execution_mode: "single-agent",
      main_model: "opus",
      subagent_model: "sonnet"
    });
    const base = resolveProviderProcesses(profile, undefined);
    expect(applyRoleRoutingToProcesses(base, profile, "implement").claude?.model).toBe(base.claude?.model);
  });

  test("Codex worker gets role-aware model via --role-model", () => {
    const profile = resolveExecutionProfile({
      provider: "codex",
      role_models: { implement: "gpt-5.5-mini" }
    });
    const base = resolveProviderProcesses(profile, undefined);
    const overlay = applyRoleRoutingToProcesses(base, profile, "implement");
    expect(overlay.codex?.model).toBe("gpt-5.5-mini");
  });
});
