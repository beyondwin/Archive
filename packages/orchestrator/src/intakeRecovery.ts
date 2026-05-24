import type {
  IntakeFinding,
  IntakeRepairAction,
  WaygentIntakeRecovery
} from "@waygent/contracts";
import type { FileClaim } from "@waygent/runway-control";
import {
  normalizeWaygentPlanInput,
  type NormalizedWaygentPlan
} from "./planNormalizer";
import { scaffoldWaygentTask } from "./planScaffold";
import {
  extractSuperpowersPlan,
  type ExtractedPlanTask
} from "./planAdapters/planClaimExtraction";
import {
  buildProjectScriptCatalog,
  type ProjectScriptCatalog
} from "./planAdapters/projectScriptCatalog";
import { classifyVerificationCommand } from "./planAdapters/verificationPolicy";
import { mergeIntakeRepair } from "./intakeRepairPlanner";

export interface RecoverWaygentPlanInput {
  markdown: string;
  path: string | null;
  workspace: string;
  spec_markdown: string;
  spec_path: string | null;
  unsafe_verification?: boolean;
  infer_risk?: boolean;
}

export interface RecoveredWaygentPlan {
  status: WaygentIntakeRecovery["status"];
  normalized_plan: NormalizedWaygentPlan;
  report: WaygentIntakeRecovery;
}

const DESTRUCTIVE_COMMAND = /\b(rm\s+-rf|git\s+reset\s+--hard|git\s+clean\s+-fd|drop\s+table|kubectl\s+delete)\b/i;

export function recoverWaygentPlanInput(input: RecoverWaygentPlanInput): RecoveredWaygentPlan {
  const startedAt = new Date().toISOString();
  try {
    const normalized = normalizeWaygentPlanInput({
      markdown: input.markdown,
      path: input.path,
      workspace: input.workspace,
      ...(input.unsafe_verification !== undefined ? { unsafe_verification: input.unsafe_verification } : {}),
      ...(input.infer_risk !== undefined ? { infer_risk: input.infer_risk } : {})
    });
    const extracted = extractSuperpowersPlan(input.markdown);
    const catalog = buildProjectScriptCatalog(input.workspace);
    const normalizedIds = new Set(extracted.tasks.map((task) => taskIdFor(task)));
    const merge = mergeIntakeRepair({
      extracted,
      strict_error: null,
      normalized_task_ids: normalizedIds,
      plan_path: input.path,
      workspace: input.workspace,
      catalog
    });
    return {
      status: "not_needed",
      normalized_plan: normalized,
      report: {
        status: "not_needed",
        started_at: startedAt,
        completed_at: new Date().toISOString(),
        normalized_plan_ref: null,
        recovery_report_ref: null,
        findings: [],
        repair_actions: [],
        can_start: true,
        confidence: "deterministic",
        question: null,
        strict_task_status: merge.strict_task_status,
        fallback_task_status: merge.fallback_task_status,
        merged_task_status: merge.merged_task_status,
        blocked_tasks: merge.blocked_tasks,
        extract_report_ref: "artifacts/intake/extract-report.json"
      }
    };
  } catch (error) {
    return deterministicRepair(input, startedAt, error instanceof Error ? error.message : String(error));
  }
}

function deterministicRepair(
  input: RecoverWaygentPlanInput,
  startedAt: string,
  strictError: string
): RecoveredWaygentPlan {
  const findings: IntakeFinding[] = [{
    code: "task_body_not_yaml",
    severity: "warning",
    message: strictError,
    task_id: null,
    evidence_refs: planEvidence(input.path)
  }];
  const actions: IntakeRepairAction[] = [];
  const extracted = extractSuperpowersPlan(input.markdown);
  const catalog = buildProjectScriptCatalog(input.workspace);
  const merge = mergeIntakeRepair({
    extracted,
    strict_error: strictError,
    normalized_task_ids: new Set(),
    plan_path: input.path,
    workspace: input.workspace,
    catalog
  });
  findings.push(...merge.findings);
  const tasks = extracted.tasks.map((section) =>
    recoverSection(section, findings, input.path, input.workspace, catalog)
  );
  for (let index = 1; index < tasks.length; index += 1) {
    tasks[index]!.dependencies = [tasks[index - 1]!.id];
  }
  const blocking = findings.filter((finding) => finding.severity === "blocking");
  const canStart = tasks.length > 0 && blocking.length === 0;
  const status: WaygentIntakeRecovery["status"] = canStart ? "recovered" : "decision_required";
  const normalizedMarkdown = canStart
    ? [
      "# Normalized Waygent Plan",
      "",
      `Source: ${input.path || "inline"}`,
      "",
      ...tasks.map((task) => scaffoldWaygentTask(task))
    ].join("\n")
    : input.markdown;

  if (canStart) {
    actions.push({
      action: "deterministic_markdown_intake_repair",
      status: "applied",
      reason: "Recovered executable task blocks from markdown headings, path references, and safe verification commands.",
      evidence_refs: ["artifacts/intake/normalized-plan.md"]
    });
  } else {
    actions.push({
      action: "deterministic_markdown_intake_repair",
      status: "blocked",
      reason: "High-risk ambiguity prevents automatic execution.",
      evidence_refs: planEvidence(input.path)
    });
  }

  const report: WaygentIntakeRecovery = {
    status,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    normalized_plan_ref: canStart ? "artifacts/intake/normalized-plan.md" : null,
    recovery_report_ref: "artifacts/intake/recovery-report.json",
    findings,
    repair_actions: actions,
    can_start: canStart,
    confidence: canStart ? "deterministic" : "blocked",
    question: canStart ? null : questionFor(blocking),
    strict_task_status: merge.strict_task_status,
    fallback_task_status: merge.fallback_task_status,
    merged_task_status: merge.merged_task_status,
    blocked_tasks: merge.blocked_tasks,
    extract_report_ref: "artifacts/intake/extract-report.json"
  };

  return {
    status,
    normalized_plan: {
      markdown: normalizedMarkdown,
      path: input.path,
      mode: canStart ? "superpowers" : "native",
      task_count: canStart ? tasks.length : 0,
      diagnostics: findings.map((finding) => `${finding.code}: ${finding.message}`)
    },
    report
  };
}

function recoverSection(
  section: ExtractedPlanTask,
  findings: IntakeFinding[],
  planPath: string | null,
  workspace: string,
  catalog: ProjectScriptCatalog
) {
  const taskId = taskIdFor(section);
  const evidenceRefs = [...planEvidence(planPath), `plan:task-${section.number}`];
  const fileClaims: FileClaim[] = section.explicit_file_claims.length > 0
    ? section.explicit_file_claims
    : section.prose_file_claims;
  const verify = section.fenced_commands.filter((command) =>
    classifyVerificationCommand({ command, workspace, catalog }).status === "safe"
  );
  if (DESTRUCTIVE_COMMAND.test(section.body)) {
    findings.push({
      code: "destructive_command_candidate",
      severity: "blocking",
      message: `Task ${section.number} contains a destructive command candidate.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  if (fileClaims.length > 0) {
    findings.push({
      code: "file_claims_in_prose",
      severity: section.explicit_file_claims.length > 0 ? "info" : "warning",
      message: `Recovered ${fileClaims.length} file claim(s).`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  if (verify.length > 0) {
    findings.push({
      code: "verification_command_in_prose",
      severity: "warning",
      message: `Recovered ${verify.length} verification command(s) from prose.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  return {
    id: taskId,
    title: section.title,
    dependencies: [] as string[],
    file_claims: fileClaims,
    risk: "high" as const,
    verify,
    instructions: instructionLines(section.body)
  };
}

function instructionLines(body: string): string[] {
  return body.split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("```") && !line.startsWith("#"))
    .slice(0, 20);
}

function questionFor(blocking: IntakeFinding[]): string {
  if (blocking.some((finding) => finding.code === "destructive_command_candidate" || finding.code === "unsafe_verification_command")) {
    return "The plan contains a destructive command candidate. Confirm the intended safe replacement before execution.";
  }
  if (blocking.some((finding) => finding.code === "verification_claim_mismatch")) {
    return "A verification command references paths outside the task claims. Add matching file claims or narrow the verification command.";
  }
  return "Waygent could not recover a safe executable plan. Provide explicit file claims and verification commands.";
}

function planEvidence(path: string | null): string[] {
  return [path ? `plan:${path}` : "plan:inline"];
}

function taskIdFor(section: ExtractedPlanTask): string {
  return `task_${section.number}_${slugify(section.title)}`;
}

function slugify(title: string): string {
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return slug || "task";
}
