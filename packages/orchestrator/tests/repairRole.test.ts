import { describe, expect, test } from "bun:test";
import {
  defaultProfiles,
  isWorkerRoleSlot,
  resolveExecutionProfile,
  roleProfileFor,
  ROLE_SLOTS
} from "../src/executionProfile";

describe("repair worker role", () => {
  test("ROLE_SLOTS includes repair", () => {
    expect(ROLE_SLOTS).toContain("repair");
  });

  test("isWorkerRoleSlot accepts repair", () => {
    expect(isWorkerRoleSlot("repair")).toBe(true);
  });

  test("defaultProfiles assign sensible repair model per provider", () => {
    expect(defaultProfiles.claude.roles!.repair).toEqual({ model: "sonnet", reasoning: "medium" });
    expect(defaultProfiles.codex.roles!.repair).toEqual({ model: "gpt-5.5", reasoning: "medium" });
    expect(defaultProfiles.fake.roles!.repair).toEqual({ model: "fake", reasoning: "medium" });
  });

  test("resolveExecutionProfile fills repair slot", () => {
    const profile = resolveExecutionProfile({ provider: "claude" });
    expect(profile.roles!.repair).toBeDefined();
    expect(roleProfileFor(profile, "repair").model).toBe("sonnet");
  });

  test("--role-model repair=opus override wins over preset", () => {
    const profile = resolveExecutionProfile({
      provider: "claude",
      role_models: { repair: "opus" },
      role_reasoning: { repair: "high" }
    });
    expect(roleProfileFor(profile, "repair")).toEqual({ model: "opus", reasoning: "high" });
  });
});
