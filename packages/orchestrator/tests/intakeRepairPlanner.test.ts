import { describe, expect, test } from "bun:test";
import { mergeIntakeRepair } from "../src/intakeRepairPlanner";
import { extractSuperpowersPlan } from "../src/planAdapters/planClaimExtraction";

const plan = `
# Demo

### Task 1: Kotlin Task

**Files:**
- Modify: \`fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt\`

Run:

\`\`\`bash
./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --no-daemon
\`\`\`

### Task 2: Unsafe Task

**Files:**
- Modify: \`README.md\`

Run:

\`\`\`bash
git reset --hard
\`\`\`
`;

describe("intake repair planner", () => {
  test("preserves explicit claims and reports unsafe verification by task", () => {
    const extracted = extractSuperpowersPlan(plan);
    const merged = mergeIntakeRepair({
      extracted,
      strict_error: "Task 2 has unsafe verification command",
      normalized_task_ids: new Set(["task_1_kotlin_task"]),
      plan_path: "/tmp/plan.md",
      workspace: "/tmp/workspace",
      catalog: null
    });

    expect(merged.merged_task_status).toEqual([
      {
        task_id: "task_1_kotlin_task",
        title: "Kotlin Task",
        status: "normalized",
        file_claim_count: 1,
        verification_command_count: 1,
        blockers: []
      },
      {
        task_id: "task_2_unsafe_task",
        title: "Unsafe Task",
        status: "blocked",
        file_claim_count: 1,
        verification_command_count: 0,
        blockers: ["missing_verification_for_source_mutation", "unsafe_verification_command"]
      }
    ]);
    expect(merged.findings).toContainEqual(expect.objectContaining({
      code: "unsafe_verification_command",
      task_id: "task_2_unsafe_task",
      severity: "blocking"
    }));
  });

  test("reports extractor policy gaps instead of false missing file claims", () => {
    const extracted = extractSuperpowersPlan(plan);
    const merged = mergeIntakeRepair({
      extracted,
      strict_error: "fallback failed to read Kotlin paths",
      normalized_task_ids: new Set(),
      plan_path: "/tmp/plan.md",
      workspace: "/tmp/workspace",
      catalog: null
    });

    expect(merged.findings.some((finding) => finding.code === "extractor_policy_gap")).toBe(false);
    expect(merged.merged_task_status[0]?.file_claim_count).toBe(1);
  });
});
