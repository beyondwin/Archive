import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
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
});
