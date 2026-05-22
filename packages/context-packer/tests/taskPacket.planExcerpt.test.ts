import { describe, expect, test } from "bun:test";
import { buildTaskPacket } from "../src/taskPacket";

function baseInput(overrides: { title: string; plan_body?: string; max_chars?: number }) {
  return {
    run_id: "run_planexcerpt",
    task: {
      id: "task_3",
      title: overrides.title,
      dependencies: [],
      file_claims: [],
      risk: "low" as const,
      verification_commands: []
    },
    role: "implement" as const,
    plan_excerpt: "",
    spec_excerpt: "",
    plan_body: overrides.plan_body,
    max_chars: overrides.max_chars
  };
}

describe("buildTaskPacket — plan_excerpt cap", () => {
  test("title-only when no plan_body", () => {
    const packet = buildTaskPacket(baseInput({ title: "Hello" }));
    expect(packet.plan_excerpt).toBe("Hello");
    expect(packet.plan_body_truncated).toBe(false);
  });

  test("body inlined under cap", () => {
    const packet = buildTaskPacket(baseInput({ title: "Hello", plan_body: "Step 1: do it." }));
    expect(packet.plan_excerpt).toBe("Hello\n\nStep 1: do it.");
    expect(packet.plan_body_truncated).toBe(false);
  });

  test("body truncated when over cap", () => {
    const body = "x".repeat(20_000);
    const packet = buildTaskPacket(baseInput({ title: "T", plan_body: body, max_chars: 60_000 }));
    expect(packet.plan_excerpt.length).toBeLessThanOrEqual(12_000);
    expect(packet.plan_body_truncated).toBe(true);
    expect(packet.plan_excerpt.endsWith("[truncated]")).toBe(true);
  });

  test("hard cap respected even when 40% of max_chars > 12000", () => {
    const packet = buildTaskPacket(baseInput({ title: "T", plan_body: "y".repeat(30_000), max_chars: 100_000 }));
    expect(packet.plan_excerpt.length).toBeLessThanOrEqual(12_000);
    expect(packet.plan_body_truncated).toBe(true);
  });

  test("small max_chars yields a small derived planLimit", () => {
    const packet = buildTaskPacket(baseInput({ title: "T", plan_body: "z".repeat(500), max_chars: 1_000 }));
    expect(packet.plan_excerpt.length).toBeLessThanOrEqual(Math.floor(1_000 * 0.4));
    expect(packet.plan_body_truncated).toBe(true);
  });
});
