import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { discoverPlan, resolvePlanInput, resolveSpecInput } from "../src/planDiscovery";

const legacyFence = [["agent", "runway"].join(""), "task"].join("-");

const plan = (id: string) => `
\`\`\`yaml waygent-task
id: ${id}
title: ${id}
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`;

const legacyPlan = (id: string) => `
\`\`\`yaml ${legacyFence}
id: ${id}
title: ${id}
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`;

describe("Waygent plan discovery", () => {
  test("discovers the newest Waygent plan by filename date", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-plan-"));
    mkdirSync(join(root, "docs", "migration"), { recursive: true });
    writeFileSync(join(root, "docs", "migration", "2026-05-20-old.md"), plan("old_task"));
    writeFileSync(join(root, "docs", "migration", "2026-05-21-new.md"), plan("new_task"));

    const found = discoverPlan({ workspace: root, latest: true });

    expect(found.path?.endsWith("2026-05-21-new.md")).toBe(true);
    expect(found.markdown).toContain("id: new_task");
  });

  test("filters topic matches against filename and heading text", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-topic-"));
    mkdirSync(join(root, "docs", "plan"), { recursive: true });
    writeFileSync(join(root, "docs", "plan", "2026-05-21-console-runtime.md"), plan("console_task"));

    const found = resolvePlanInput({ workspace: root, topic: "console runtime" });

    expect(found.path?.endsWith("2026-05-21-console-runtime.md")).toBe(true);
  });

  test("resolves plan basenames from approved superpowers plan directories", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-superpowers-plan-"));
    mkdirSync(join(root, "docs", "superpowers", "plans"), { recursive: true });
    writeFileSync(join(root, "docs", "superpowers", "plans", "2026-05-22-runtime.md"), plan("runtime_task"));

    const found = resolvePlanInput({ workspace: root, plan_path: "2026-05-22-runtime.md" });

    expect(found.path?.endsWith("docs/superpowers/plans/2026-05-22-runtime.md")).toBe(true);
    expect(found.markdown).toContain("id: runtime_task");
  });

  test("resolves spec basenames from approved superpowers spec directories", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-superpowers-spec-"));
    mkdirSync(join(root, "docs", "superpowers", "specs"), { recursive: true });
    writeFileSync(join(root, "docs", "superpowers", "specs", "2026-05-22-runtime-design.md"), "# Runtime Design\n");

    const found = resolveSpecInput({ workspace: root, spec: "2026-05-22-runtime-design.md" });

    expect(found.path?.endsWith("docs/superpowers/specs/2026-05-22-runtime-design.md")).toBe(true);
    expect(found.markdown).toBe("# Runtime Design\n");
  });

  test("fails missing spec filenames instead of treating them as inline markdown", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-missing-spec-"));

    expect(() => resolveSpecInput({ workspace: root, spec: "2026-05-22-runtime-desgin.md" })).toThrow(
      /spec not found/
    );
  });

  test("does not resolve directory-bearing plan typos by basename fallback", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-plan-path-typo-"));
    mkdirSync(join(root, "docs", "superpowers", "plans"), { recursive: true });
    mkdirSync(join(root, "docs", "plans"), { recursive: true });
    writeFileSync(join(root, "docs", "plans", "runtime.md"), plan("wrong_task"));

    expect(() => resolvePlanInput({ workspace: root, plan_path: "docs/superpowers/plans/runtime.md" })).toThrow(
      /plan not found/
    );
  });

  test("ignores legacy task plans during latest discovery", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-legacy-plan-"));
    mkdirSync(join(root, "docs", "migration"), { recursive: true });
    writeFileSync(join(root, "docs", "migration", "2026-05-22-legacy.md"), legacyPlan("legacy_task"));

    expect(() => discoverPlan({ workspace: root, latest: true })).toThrow("no Waygent plan found");
  });
});
