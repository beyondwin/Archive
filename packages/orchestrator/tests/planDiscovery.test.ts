import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { discoverPlan, resolvePlanInput } from "../src/planDiscovery";

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

  test("ignores legacy task plans during latest discovery", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-legacy-plan-"));
    mkdirSync(join(root, "docs", "migration"), { recursive: true });
    writeFileSync(join(root, "docs", "migration", "2026-05-22-legacy.md"), legacyPlan("legacy_task"));

    expect(() => discoverPlan({ workspace: root, latest: true })).toThrow("no Waygent plan found");
  });
});
