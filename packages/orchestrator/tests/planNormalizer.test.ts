import { describe, expect, test } from "bun:test";
import { parseWaygentPlan } from "../src/planParser";
import { normalizeWaygentPlanInput } from "../src/planNormalizer";

const executableSuperpowersPlan = `
# Demo Implementation Plan

## Task 1: Update README Contract

**Files:**

- Modify: \`README.md\`
- Create: \`docs/runtime.md\`

- [ ] **Step 1: Write the failing behavior test**

Run:

\`\`\`bash
bun test packages/orchestrator/tests/planNormalizer.test.ts
graphify update .
git add README.md
\`\`\`

## Task 2: Wire CLI Surface

**Files:**

- Modify: \`apps/cli/src/index.ts\`
- Modify: \`apps/cli/tests/cli.test.ts\`

- [ ] **Step 1: Expose the new behavior**

Run:

\`\`\`bash
bun test apps/cli/tests/cli.test.ts
\`\`\`
`;

describe("Waygent plan normalizer", () => {
  test("leaves native waygent-task plans unchanged", () => {
    const native = `
\`\`\`yaml waygent-task
id: task_native
title: Native task
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`;

    const normalized = normalizeWaygentPlanInput({ markdown: native, path: "/tmp/native.md" });

    expect(normalized.mode).toBe("native");
    expect(normalized.markdown).toBe(native);
    expect(normalized.diagnostics).toEqual([]);
  });

  test("converts explicit superpowers implementation tasks into executable Waygent task blocks", () => {
    const normalized = normalizeWaygentPlanInput({ markdown: executableSuperpowersPlan, path: "/tmp/plan.md" });
    const parsed = parseWaygentPlan(normalized.markdown);

    expect(normalized.mode).toBe("superpowers");
    expect(normalized.task_count).toBe(2);
    expect(normalized.diagnostics).toContain("risk defaulted to high for 2 normalized tasks");
    expect(parsed.tasks).toHaveLength(2);
    expect(parsed.tasks[0]).toMatchObject({
      id: "task_1_update_readme_contract",
      title: "Update README Contract",
      dependencies: [],
      risk: "high",
      file_claims: [
        { path: "README.md", mode: "owned" },
        { path: "docs/runtime.md", mode: "owned" }
      ],
      verification_commands: ["bun test packages/orchestrator/tests/planNormalizer.test.ts"]
    });
    expect(parsed.tasks[0]?.instructions.join("\n")).toContain("Step 1: Write the failing behavior test");
    expect(parsed.tasks[0]?.instructions.join("\n")).toContain("graphify update .");
    expect(parsed.tasks[1]?.dependencies).toEqual(["task_1_update_readme_contract"]);
    expect(parsed.tasks[1]?.verification_commands).toEqual(["bun test apps/cli/tests/cli.test.ts"]);
    expect(parsed.tasks[0]?.verification_commands).not.toContain("graphify update .");
    expect(normalized.markdown).not.toContain("git add README.md");
  });

  test("rejects superpowers tasks without explicit file claims", () => {
    expect(() =>
      normalizeWaygentPlanInput({
        markdown: `
# Demo Implementation Plan

## Task 1: Missing Files

Run:

\`\`\`bash
bun test packages/orchestrator/tests/planNormalizer.test.ts
\`\`\`
`,
        path: "/tmp/plan.md"
      })
    ).toThrow(/cannot normalize superpowers implementation plan.*Task 1.*missing explicit file claims/s);
  });

  test("rejects superpowers tasks without safe verification commands", () => {
    expect(() =>
      normalizeWaygentPlanInput({
        markdown: `
# Demo Implementation Plan

## Task 1: Only Mutating Commands

**Files:**

- Modify: \`README.md\`

Run:

\`\`\`bash
git add README.md
git commit -m "update readme"
\`\`\`
`,
        path: "/tmp/plan.md"
      })
    ).toThrow(/cannot normalize superpowers implementation plan.*Task 1.*missing safe verification commands/s);
  });
});
