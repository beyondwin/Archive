import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { readFileSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseWaygentPlan } from "../src/planParser";
import { normalizeWaygentPlanInput } from "../src/planNormalizer";

const planMarkdown = readFileSync(
  join(import.meta.dir, "fixtures", "fixture_lab_plan.md"),
  "utf8"
);

let workspace: string;

beforeEach(() => {
  workspace = mkdtempSync(join(tmpdir(), "fixture-lab-"));
  writeFileSync(
    join(workspace, "package.json"),
    JSON.stringify({ scripts: { check: "bun run check", scenarios: "echo scenarios" } })
  );
});

afterEach(() => {
  rmSync(workspace, { recursive: true, force: true });
});

describe("planNormalizer fixture-lab integration", () => {
  test("accepts fixture-lab plan with catalog and infers per-task risk", () => {
    const normalized = normalizeWaygentPlanInput({
      markdown: planMarkdown,
      path: "/tmp/fixture_lab_plan.md",
      workspace
    });

    expect(normalized.mode).toBe("superpowers");
    expect(normalized.task_count).toBe(3);

    const parsed = parseWaygentPlan(normalized.markdown);
    expect(parsed.tasks).toHaveLength(3);
    expect(parsed.tasks[0]?.risk).toBe("low");
    expect(parsed.tasks[1]?.risk).toBe("medium");
    expect(parsed.tasks[2]?.risk).toBe("low");

    expect(normalized.diagnostics.some((d) => d.startsWith("risk inferred for 3"))).toBe(true);
    expect(normalized.diagnostics.some((d) => d.startsWith("project script catalog applied"))).toBe(
      true
    );
  });

  test("emits a verification quality warning when verify is trivial", () => {
    const normalized = normalizeWaygentPlanInput({
      markdown: planMarkdown,
      path: "/tmp/fixture_lab_plan.md",
      workspace
    });

    const trivialWarning = normalized.diagnostics.find(
      (d) => d.includes('Task 3') && d.includes("verification quality warning")
    );

    expect(trivialWarning).toBeDefined();
    expect(trivialWarning).toContain("all verify commands are trivial");
  });

  test("strict mode rejects plans whose verify references unclaimed paths", () => {
    const strictBad = `
# Fixture Lab Strict Failure

## Task 1: Unclaimed verification path

**Files:**

- Modify: \`README.md\`

Run:

\`\`\`bash
bun test packages/orchestrator/tests/planNormalizer.test.ts
\`\`\`
`;

    expect(() =>
      normalizeWaygentPlanInput({
        markdown: strictBad,
        path: "/tmp/strict.md"
      })
    ).toThrow(/verification command references unclaimed path/);
  });

  test("unsafe_verification downgrades strict errors to diagnostics", () => {
    const strictBad = `
# Fixture Lab Strict Failure

## Task 1: Unclaimed verification path

**Files:**

- Modify: \`README.md\`

Run:

\`\`\`bash
bun test packages/orchestrator/tests/planNormalizer.test.ts
\`\`\`
`;

    const normalized = normalizeWaygentPlanInput({
      markdown: strictBad,
      path: "/tmp/strict.md",
      unsafe_verification: true
    });

    expect(normalized.task_count).toBe(1);
    expect(
      normalized.diagnostics.some((d) =>
        d.includes("verification command references unclaimed path")
      )
    ).toBe(true);
    expect(
      normalized.diagnostics.some((d) => d.startsWith("unsafe_verification"))
    ).toBe(true);
  });

  test("catalog extends safe verification allowlist", () => {
    const planUsingCatalog = `
# Catalog plan

## Task 1: Use a catalog command for verification

**Files:**

- Modify: \`packages/orchestrator/src/foo.ts\`

Run:

\`\`\`bash
bun run scenarios
\`\`\`
`;

    // Without workspace/catalog: "bun run scenarios" is not in SAFE_COMMAND_STARTS
    // (only specific bun run subcommands are). Strict mode rejects.
    expect(() =>
      normalizeWaygentPlanInput({
        markdown: planUsingCatalog,
        path: "/tmp/catalog.md"
      })
    ).toThrow(/missing safe verification commands/);

    // With workspace whose package.json declares a "scenarios" script,
    // catalog accepts "bun run scenarios" as safe verification.
    const normalized = normalizeWaygentPlanInput({
      markdown: planUsingCatalog,
      path: "/tmp/catalog.md",
      workspace
    });

    const parsed = parseWaygentPlan(normalized.markdown);
    expect(parsed.tasks[0]?.verification_commands).toEqual(["bun run scenarios"]);
  });
});
