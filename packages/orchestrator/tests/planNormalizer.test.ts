import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseWaygentPlan } from "../src/planParser";
import { normalizeWaygentPlanInput } from "../src/planNormalizer";

const graphifyAuditCommand = ["graphify", "update", "."].join(" ");

const executableSuperpowersPlan = `
# Demo Implementation Plan

### Task 1: Update README Contract

**Files:**

- Modify: \`README.md\`
- Create: \`docs/runtime.md\`
- Modify: \`packages/orchestrator/tests/planNormalizer.test.ts\`

- [ ] **Step 1: Write the failing behavior test**

Run:

\`\`\`bash
bun test packages/orchestrator/tests/planNormalizer.test.ts
${graphifyAuditCommand}
git add README.md
\`\`\`

### Task 2: Wire CLI Surface

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
        { path: "docs/runtime.md", mode: "owned" },
        { path: "packages/orchestrator/tests/planNormalizer.test.ts", mode: "owned" }
      ],
      verification_commands: ["bun test packages/orchestrator/tests/planNormalizer.test.ts"]
    });
    expect(parsed.tasks[0]?.instructions.join("\n")).toContain("Step 1: Write the failing behavior test");
    expect(parsed.tasks[0]?.instructions.join("\n")).toContain(graphifyAuditCommand);
    expect(parsed.tasks[1]?.dependencies).toEqual(["task_1_update_readme_contract"]);
    expect(parsed.tasks[1]?.verification_commands).toEqual(["bun test apps/cli/tests/cli.test.ts"]);
    expect(parsed.tasks[0]?.verification_commands).not.toContain(graphifyAuditCommand);
    expect(normalized.markdown).not.toContain("git add README.md");
  });

  test("rejects superpowers tasks without recoverable file claims", () => {
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
    ).toThrow(/cannot normalize superpowers implementation plan.*Task 1.*missing recoverable file claims/s);
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

  test("rejects mixed safe and unsafe verification blocks", () => {
    expect(() =>
      normalizeWaygentPlanInput({
        markdown: `
# Demo Implementation Plan

## Task 1: Mixed Verification

**Files:**

- Modify: \`README.md\`

Run:

\`\`\`bash
git diff --check -- README.md
rm -rf build
\`\`\`
`,
        path: "/tmp/plan.md"
      })
    ).toThrow(/Task 1.*unsafe verification command.*rm -rf build/s);
  });

  test("rejects superpowers verification commands that reference unclaimed files", () => {
    expect(() =>
      normalizeWaygentPlanInput({
        markdown: `
# Demo Implementation Plan

## Task 1: Missing Verification Claim

**Files:**

- Modify: \`README.md\`

Run:

\`\`\`bash
bun test packages/orchestrator/tests/planNormalizer.test.ts
\`\`\`
`,
        path: "/tmp/plan.md"
      })
    ).toThrow(/Task 1.*verification command references unclaimed path packages\/orchestrator\/tests\/planNormalizer\.test\.ts/s);
  });

  test("allows verification commands that reference files claimed by another task", () => {
    const normalized = normalizeWaygentPlanInput({
      markdown: `
# Demo Implementation Plan

## Task 1: Own Shared Test

**Files:**

- Modify: \`packages/orchestrator/tests/planNormalizer.test.ts\`

Run:

\`\`\`bash
bun test packages/orchestrator/tests/planNormalizer.test.ts
\`\`\`

## Task 2: Verify Shared Test

**Files:**

- Modify: \`README.md\`

Run:

\`\`\`bash
bun test packages/orchestrator/tests/planNormalizer.test.ts
\`\`\`
`,
      path: "/tmp/plan.md"
    });

    expect(normalized.task_count).toBe(2);
  });

  test("normalizes tasks that provide recoverable prose file claims", () => {
    const normalized = normalizeWaygentPlanInput({
      markdown: `
# Demo Implementation Plan

## Task 1: Update Referenced Docs

Inspect \`README.md\` and update \`docs/runtime.md\`.

Run:

\`\`\`bash
git diff --check -- docs/runtime.md
\`\`\`
`,
      path: "/tmp/prose-claims.md"
    });
    const parsed = parseWaygentPlan(normalized.markdown);

    expect(normalized.mode).toBe("superpowers");
    expect(parsed.tasks[0]).toMatchObject({
      id: "task_1_update_referenced_docs",
      file_claims: [
        { path: "README.md", mode: "read_only" },
        { path: "docs/runtime.md", mode: "owned" }
      ],
      verification_commands: ["git diff --check -- docs/runtime.md"]
    });
  });

  test("tolerates generator commands mixed into superpowers verification fences", () => {
    const normalized = normalizeWaygentPlanInput({
      markdown: `
# Console Implementation Plan

## Task 1: Implement Console Bundle Change

**Files:**

- Modify: \`fixthis-mcp/src/main/console/preview.js\`
- Modify: \`fixthis-mcp/src/main/resources/console/app.js\`

Run:

\`\`\`bash
node --test scripts/studioReliabilityContract-test.mjs
FIXTHIS_BUNDLE_REPRODUCIBLE=1 node scripts/build-console-assets.mjs
\`\`\`
`,
      path: "/tmp/console-plan.md"
    });
    const parsed = parseWaygentPlan(normalized.markdown);

    expect(parsed.tasks[0]?.verification_commands).toEqual([
      "node --test scripts/studioReliabilityContract-test.mjs"
    ]);
    expect(parsed.tasks[0]?.instructions.join("\n")).toContain(
      "FIXTHIS_BUNDLE_REPRODUCIBLE=1 node scripts/build-console-assets.mjs"
    );
    expect(normalized.diagnostics.join("\n")).toContain("ignored non-verification command");
  });

  test("normalizes writing-plans RED-only tasks as expected-failure verification", () => {
    const normalized = normalizeWaygentPlanInput({
      markdown: `
# Red Contract Implementation Plan

## Task 1: Lock Contract

**Files:**

- Modify: \`tests/red-contract.test.ts\`

- [ ] **Step 1: Write the failing test**

\`\`\`ts
test("new contract", () => expect(false).toBe(true));
\`\`\`

- [ ] **Step 2: Run test to verify it fails**

Run:

\`\`\`bash
bun test tests/red-contract.test.ts
\`\`\`

Expected: FAIL because the implementation does not exist yet.
`,
      path: "/tmp/red-plan.md"
    });
    const parsed = parseWaygentPlan(normalized.markdown);

    expect(normalized.markdown).toContain("verify_fail:");
    expect(parsed.tasks[0]?.verification_commands).toEqual(["bun test tests/red-contract.test.ts"]);
    expect(parsed.tasks[0]?.verification_expectations).toEqual([
      { command: "bun test tests/red-contract.test.ts", expected_exit: "nonzero" }
    ]);
  });

  test("normalizes writing-plans mixed RED/GREEN tasks to final passing verification only", () => {
    const normalized = normalizeWaygentPlanInput({
      markdown: `
# Feature Implementation Plan

## Task 1: Implement Feature

**Files:**

- Modify: \`src/feature.ts\`
- Test: \`tests/feature.test.ts\`

- [ ] **Step 1: Write the failing test**

Run: \`bun test tests/feature.test.ts\`
Expected: FAIL because feature() is not exported.

- [ ] **Step 2: Implement feature**

\`\`\`ts
export function feature() { return true; }
\`\`\`

- [ ] **Step 3: Run test to verify it passes**

Run: \`bun test tests/feature.test.ts\`
Expected: PASS.
`,
      path: "/tmp/mixed-plan.md"
    });
    const parsed = parseWaygentPlan(normalized.markdown);

    expect(normalized.markdown).not.toContain("verify_fail:");
    expect(parsed.tasks[0]?.verification_commands).toEqual(["bun test tests/feature.test.ts"]);
    expect(parsed.tasks[0]?.verification_expectations).toEqual([
      { command: "bun test tests/feature.test.ts", expected_exit: "zero" }
    ]);
  });

  test("normalizes claimless final verification as a read-only workspace task", () => {
    const normalized = normalizeWaygentPlanInput({
      markdown: `
# Console Implementation Plan

## Task 1: Final Verification

**Files:**
- No source edits unless verification exposes failures.

Run:

\`\`\`bash
node --test scripts/studioReliabilityContract-test.mjs
FIXTHIS_BUNDLE_REPRODUCIBLE=1 node scripts/build-console-assets.mjs
git diff --check
\`\`\`
`,
      path: "/tmp/final-verification.md"
    });
    const parsed = parseWaygentPlan(normalized.markdown);

    expect(parsed.tasks[0]).toMatchObject({
      id: "task_1_final_verification",
      file_claims: [{ path: ".", mode: "read_only" }],
      verification_commands: [
        "node --test scripts/studioReliabilityContract-test.mjs",
        "git diff --check"
      ]
    });
  });

  test("ignores ## Task N: headings that live inside fenced code blocks", () => {
    const planWithFencedFixture = [
      "# Demo Plan",
      "",
      "### Task 1: Real Task",
      "",
      "**Files:**",
      "",
      "- Modify: `README.md`",
      "",
      "Run:",
      "",
      "```bash",
      "bun test",
      "```",
      "",
      "Below is a unit-test fixture that demonstrates the parser format.",
      "It is NOT a real task and must not be normalized:",
      "",
      "```ts",
      "const FIXTURE = `",
      "## Task 99: This Is Demo Text Inside A String Literal",
      "Some prose with no Files: section and no Run: block.",
      "`;",
      "```",
      ""
    ].join("\n");

    const normalized = normalizeWaygentPlanInput({
      markdown: planWithFencedFixture,
      path: "/tmp/plan.md"
    });

    expect(normalized.task_count).toBe(1);
  });

  test("normalizes memory-second-brain style plans and strips implementation-only verify commands", () => {
    const fixture = readFileSync(join(import.meta.dir, "fixtures", "memory_second_brain_plan.md"), "utf8");
    const workspace = mkdtempSync(join(tmpdir(), "waygent-memory-plan-"));
    writeFileSync(join(workspace, "package.json"), JSON.stringify({
      scripts: {
        build: "vite build",
        validate: "astro check",
        "memory:validate": "node scripts/memory/validate.mjs"
      }
    }));

    const normalized = normalizeWaygentPlanInput({
      markdown: fixture,
      path: "/tmp/memory_second_brain.md",
      workspace
    });
    const parsed = parseWaygentPlan(normalized.markdown);

    expect(normalized.mode).toBe("superpowers");
    expect(parsed.tasks).toHaveLength(2);
    expect(parsed.tasks[0]?.verification_commands).toEqual([
      "npm test -- --runInBand",
      "npm run memory:validate"
    ]);
    expect(parsed.tasks[1]?.verification_commands).toEqual([
      "npm run build",
      "npm run validate"
    ]);
    expect(parsed.tasks[0]?.instructions.join("\n")).toContain("npm install");
    expect(parsed.tasks[1]?.instructions.join("\n")).toContain("graphify update .");
    expect(normalized.markdown).not.toContain("verify:\n  - npm install");
    expect(normalized.markdown).not.toContain("verify:\n  - graphify update .");
  });
});
