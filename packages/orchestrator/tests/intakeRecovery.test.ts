import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseWaygentPlan } from "../src/planParser";
import { recoverWaygentPlanInput } from "../src/intakeRecovery";

function fixture(name: string): string {
  return readFileSync(join(import.meta.dir, "fixtures", name), "utf8");
}

describe("Waygent intake recovery", () => {
  test("recovers prose tasks with traceable file claims and verification", () => {
    const recovered = recoverWaygentPlanInput({
      markdown: fixture("intake_recovery_bad_plan.md"),
      path: "/tmp/intake_recovery_bad_plan.md",
      workspace: "/tmp/workspace",
      spec_markdown: "# Intake Recovery Design\n\n## README\nMention intake recovery.\n",
      spec_path: "/tmp/spec.md"
    });

    expect(recovered.status).toBe("recovered");
    expect(recovered.normalized_plan.task_count).toBe(1);
    expect(recovered.report.can_start).toBe(true);
    expect(recovered.report.findings.map((finding) => finding.code)).toContain("task_body_not_yaml");
    expect(recovered.report.findings.map((finding) => finding.code)).toContain("file_claims_in_prose");
    expect(recovered.report.findings.map((finding) => finding.code)).toContain("verification_command_in_prose");

    const parsed = parseWaygentPlan(recovered.normalized_plan.markdown);
    expect(parsed.tasks[0]).toMatchObject({
      id: "task_1_update_readme",
      title: "Update README",
      file_claims: [{ path: "README.md", mode: "owned" }],
      verification_commands: ["git diff --check -- README.md"]
    });
  });

  test("blocks destructive command candidates instead of repairing them", () => {
    const recovered = recoverWaygentPlanInput({
      markdown: fixture("intake_recovery_unsafe_plan.md"),
      path: "/tmp/intake_recovery_unsafe_plan.md",
      workspace: "/tmp/workspace",
      spec_markdown: "",
      spec_path: null
    });

    expect(recovered.status).toBe("decision_required");
    expect(recovered.report.can_start).toBe(false);
    expect(recovered.report.question).toContain("destructive command");
    expect(recovered.report.findings).toContainEqual(expect.objectContaining({
      code: "destructive_command_candidate",
      severity: "blocking"
    }));
  });

  test("ignores destructive-looking text in non-shell example fences", () => {
    const recovered = recoverWaygentPlanInput({
      markdown: `
# Demo Implementation Plan

## Task 1: Document cleanup guard

**Files:**

- Modify: \`README.md\`

Run:

\`\`\`bash
git diff --check -- README.md
\`\`\`

Example:

\`\`\`js
const warning = "do not run rm -rf build";
\`\`\`
`,
      path: "/tmp/example-fence.md",
      workspace: "/tmp/workspace",
      spec_markdown: "",
      spec_path: null
    });

    expect(recovered.status).toBe("recovered");
    expect(recovered.report.can_start).toBe(true);
    expect(recovered.report.findings).not.toContainEqual(expect.objectContaining({
      code: "destructive_command_candidate"
    }));
    expect(parseWaygentPlan(recovered.normalized_plan.markdown).tasks[0]?.verification_commands).toEqual([
      "git diff --check -- README.md"
    ]);
  });

  test("blocks recovery when verification references unclaimed paths", () => {
    const recovered = recoverWaygentPlanInput({
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
      path: "/tmp/strict.md",
      workspace: "/tmp/workspace",
      spec_markdown: "",
      spec_path: null
    });

    expect(recovered.status).toBe("decision_required");
    expect(recovered.normalized_plan.mode).toBe("native");
    expect(recovered.report.normalized_plan_ref).toBeNull();
    expect(recovered.report.can_start).toBe(false);
    expect(recovered.report.findings).toContainEqual(expect.objectContaining({
      code: "verification_claim_mismatch",
      severity: "blocking"
    }));
  });

  test("blocks unsafe-only verification without throwing during recovery", () => {
    const recovered = recoverWaygentPlanInput({
      markdown: `
# Demo Implementation Plan

## Task 1: Unsafe Only

**Files:**

- Modify: \`README.md\`

Run:

\`\`\`bash
npm run missing-script
\`\`\`
`,
      path: "/tmp/unsafe-only.md",
      workspace: "/tmp/workspace",
      spec_markdown: "",
      spec_path: null
    });

    expect(recovered.status).toBe("decision_required");
    expect(recovered.normalized_plan.mode).toBe("native");
    expect(recovered.report.normalized_plan_ref).toBeNull();
    expect(recovered.report.can_start).toBe(false);
    expect(recovered.report.findings).toContainEqual(expect.objectContaining({
      code: "unsafe_verification_command",
      severity: "blocking"
    }));
  });

  test("does not report Kotlin and Gradle plans as missing claims", () => {
    const recovered = recoverWaygentPlanInput({
      markdown: `
# Source Matching Trust Program

### Task 3: Improve Precise And Compact Handoff Trust Wording

**Files:**
- Modify: \`fixthis-mcp/src/test/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatterTest.kt\`
- Modify: \`fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt\`

Run:

\`\`\`bash
./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --no-daemon
\`\`\`
`,
      path: "/tmp/source-matching-trust-program.md",
      workspace: "/tmp/workspace",
      spec_markdown: "",
      spec_path: null
    });

    expect(recovered.status).toBe("recovered");
    expect(recovered.report.can_start).toBe(true);
    expect(recovered.report.findings.some((finding) => finding.message.includes("no recoverable file claim"))).toBe(false);
  });

  test("recovers memory-second-brain style plans without an operator decision", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-memory-recovery-"));
    writeFileSync(join(workspace, "package.json"), JSON.stringify({
      scripts: {
        build: "vite build",
        validate: "astro check",
        "memory:validate": "node scripts/memory/validate.mjs"
      }
    }));

    const recovered = recoverWaygentPlanInput({
      markdown: fixture("memory_second_brain_plan.md"),
      path: "/tmp/memory_second_brain.md",
      workspace,
      spec_markdown: "# Memory Second Brain\n",
      spec_path: "/tmp/memory_spec.md"
    });

    expect(recovered.status).toBe("recovered");
    expect(recovered.report.can_start).toBe(true);
    expect(recovered.report.question).toBeNull();
    expect(recovered.report.normalized_plan_ref).toBe("artifacts/intake/normalized-plan.md");
    expect(recovered.report.findings.some((finding) => finding.severity === "blocking")).toBe(false);
  });

  test("recovers the full-plan fixture with verification for every source-mutating task", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-full-plan-recovery-"));
    writeFileSync(join(workspace, "package.json"), JSON.stringify({
      scripts: {
        "source-matching:fixtures:test": "node --test scripts/source-matching-fixtures-test.mjs",
        "source-matching:fixtures:runtime": "node scripts/source-matching-fixtures.mjs runtime"
      }
    }));

    const recovered = recoverWaygentPlanInput({
      markdown: fixture("full_plan_intake_hardening.md"),
      path: "/tmp/full_plan_intake_hardening.md",
      workspace,
      spec_markdown: "# Source Matching Runtime Trust Fixtures\n",
      spec_path: "/tmp/full_plan_spec.md"
    });

    expect(recovered.status).toBe("recovered");
    expect(recovered.report.can_start).toBe(true);
    expect(recovered.report.question).toBeNull();
    expect(recovered.report.findings).not.toContainEqual(expect.objectContaining({
      code: "unsafe_verification_command"
    }));
    expect(recovered.report.merged_task_status).toHaveLength(3);
    for (const task of recovered.report.merged_task_status) {
      expect(task.file_claim_count).toBeGreaterThan(0);
      expect(task.verification_command_count).toBeGreaterThan(0);
      expect(task.blockers).not.toContain("unsafe_verification_command");
      expect(task.blockers).not.toContain("missing_verification_for_source_mutation");
    }
  });
});
