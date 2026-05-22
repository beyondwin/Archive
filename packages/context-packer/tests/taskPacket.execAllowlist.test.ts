import { describe, expect, test } from "bun:test";
import { buildTaskPacket, READ_ONLY_UTILITIES } from "../src/taskPacket";

function baseInput(overrides: {
  workspace?: string;
  project_commands?: readonly string[];
  verification_commands?: string[];
}) {
  return {
    run_id: "run_allowlist",
    task: {
      id: "task_allow",
      title: "Allowlist test",
      dependencies: [],
      file_claims: [],
      risk: "low" as const,
      verification_commands: overrides.verification_commands ?? []
    },
    role: "implement" as const,
    plan_excerpt: "Allowlist test",
    spec_excerpt: "",
    workspace: overrides.workspace,
    project_commands: overrides.project_commands
  };
}

describe("buildTaskPacket — allowed_exec_commands", () => {
  test("returns null when no workspace is provided", () => {
    const packet = buildTaskPacket(baseInput({}));
    expect(packet.allowed_exec_commands).toBeNull();
  });

  test("unions project commands, verification commands, and read-only utilities", () => {
    const packet = buildTaskPacket(
      baseInput({
        workspace: "/tmp/fake-workspace",
        project_commands: ["bun run domain:test", "npm run lint"],
        verification_commands: ["bun test packages/foo"]
      })
    );

    expect(Array.isArray(packet.allowed_exec_commands)).toBe(true);
    const list = packet.allowed_exec_commands ?? [];

    expect(list).toContain("bun run domain:test");
    expect(list).toContain("npm run lint");
    expect(list).toContain("bun test packages/foo");

    for (const utility of READ_ONLY_UTILITIES) {
      expect(list).toContain(utility);
    }

    expect(list.length).toBe(2 + 1 + READ_ONLY_UTILITIES.length);
  });

  test("preserves ordering: project commands, then verification, then read-only utilities", () => {
    const packet = buildTaskPacket(
      baseInput({
        workspace: "/tmp/fake-workspace",
        project_commands: ["bun run domain:test"],
        verification_commands: ["bun test pkg/x"]
      })
    );

    const list = packet.allowed_exec_commands ?? [];
    expect(list[0]).toBe("bun run domain:test");
    expect(list[1]).toBe("bun test pkg/x");
    expect(list[2]).toBe(READ_ONLY_UTILITIES[0]);
  });

  test("builds a non-empty allowlist even when project_commands is missing", () => {
    const packet = buildTaskPacket(
      baseInput({
        workspace: "/tmp/fake-workspace",
        verification_commands: ["bun test pkg/x"]
      })
    );

    const list = packet.allowed_exec_commands ?? [];
    expect(list).toContain("bun test pkg/x");
    expect(list).toContain("ls");
    expect(list.length).toBe(1 + READ_ONLY_UTILITIES.length);
  });

  test("read-only utilities cover required spec entries", () => {
    expect(READ_ONLY_UTILITIES).toContain("ls");
    expect(READ_ONLY_UTILITIES).toContain("cat");
    expect(READ_ONLY_UTILITIES).toContain("grep");
    expect(READ_ONLY_UTILITIES).toContain("git status");
    expect(READ_ONLY_UTILITIES).toContain("git diff");
    expect(READ_ONLY_UTILITIES).toContain("bun test");
    expect(READ_ONLY_UTILITIES).toContain("bun run check");
  });
});
