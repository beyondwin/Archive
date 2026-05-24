import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { normalizeWaygentPlanInput } from "../src/planNormalizer";
import { runPlanPreflight } from "../src/planPreflight";

describe("plan/spec preflight", () => {
  test("accepts normalized ### Task sections with claims and verification", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-plan-preflight-"));
    const normalized = normalizeWaygentPlanInput({
      path: join(workspace, "plan.md"),
      markdown: `
# Implementation Plan

### Task 1: Update README

**Files:**

- Modify: \`README.md\`

Run:

\`\`\`bash
git diff --check -- README.md
\`\`\`
`
    });

    const result = runPlanPreflight({
      workspace,
      plan_path: normalized.path,
      normalized_plan: normalized,
      spec_path: null
    });

    expect(result.status).toBe("passed");
    expect(result.errors).toEqual([]);
  });

  test("rejects escaped file claims before run state creation", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-plan-preflight-escape-"));
    const normalized = {
      path: join(workspace, "plan.md"),
      markdown: `
\`\`\`yaml waygent-task
id: task_escape
title: Escape
dependencies: []
file_claims:
  - path: ../outside.txt
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`,
      mode: "native" as const,
      task_count: 1,
      diagnostics: []
    };

    const result = runPlanPreflight({
      workspace,
      plan_path: normalized.path,
      normalized_plan: normalized,
      spec_path: null
    });

    expect(result.status).toBe("failed");
    expect(result.errors.join("\n")).toContain("escapes workspace");
  });

  test("rejects path-like missing spec inputs", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-plan-preflight-spec-"));
    const planPath = join(workspace, "plan.md");
    writeFileSync(planPath, "# plan\n");

    const result = runPlanPreflight({
      workspace,
      plan_path: planPath,
      normalized_plan: {
        path: planPath,
        markdown: `
\`\`\`yaml waygent-task
id: task_demo
title: Demo
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`,
        mode: "native",
        task_count: 1,
        diagnostics: []
      },
      spec_path: join(workspace, "missing.md")
    });

    expect(result.status).toBe("failed");
    expect(result.errors.join("\n")).toContain("spec not found");
  });

  test("rejects destructive segments after legacy native node checks", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-plan-preflight-node-"));

    const result = runPlanPreflight({
      workspace,
      plan_path: null,
      normalized_plan: {
        path: null,
        markdown: `
\`\`\`yaml waygent-task
id: task_native_node
title: Native node compatibility
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - node -e "console.log('ok')" && rm -rf build
\`\`\`
`,
        mode: "native",
        task_count: 1,
        diagnostics: []
      },
      spec_path: null
    });

    expect(result.status).toBe("failed");
    expect(result.errors.join("\n")).toContain("unsafe verification command");
  });
});
