import type { IntakeFinding, IntakeTaskRecoveryStatus } from "@waygent/contracts";
import type { ExtractedSuperpowersPlan, ExtractedPlanTask } from "./planAdapters/planClaimExtraction";
import type { ProjectScriptCatalog } from "./planAdapters/projectScriptCatalog";
import { classifyVerificationCommand } from "./planAdapters/verificationPolicy";
import { verificationClaimCoverageIssues } from "./planAdapters/verificationCoverage";

export interface IntakeRepairMergeInput {
  extracted: ExtractedSuperpowersPlan;
  strict_error: string | null;
  normalized_task_ids: Set<string>;
  plan_path: string | null;
  workspace: string;
  catalog: ProjectScriptCatalog | null;
}

export interface IntakeRepairMergeResult {
  strict_task_status: IntakeTaskRecoveryStatus[];
  fallback_task_status: IntakeTaskRecoveryStatus[];
  merged_task_status: IntakeTaskRecoveryStatus[];
  blocked_tasks: IntakeTaskRecoveryStatus[];
  findings: IntakeFinding[];
}

export function mergeIntakeRepair(input: IntakeRepairMergeInput): IntakeRepairMergeResult {
  const merged = input.extracted.tasks.map((task) => statusForTask(task, input));
  const coverageIssues = verificationClaimCoverageIssues(input.extracted.tasks.map((task) => ({
    title: task.title,
    label: taskIdFor(task),
    file_claims: task.explicit_file_claims.length > 0 ? task.explicit_file_claims : task.prose_file_claims,
    verification_commands: safeVerificationCommands(task, input)
  })));
  for (const issue of coverageIssues) {
    const target = merged.find((task) => task.title === issue.task_title);
    if (!target || input.normalized_task_ids.has(target.task_id)) continue;
    target.status = "blocked";
    target.blockers = [...new Set([...target.blockers, "verification_claim_mismatch"])];
  }
  const blocked = merged.filter((task) => task.status === "blocked");
  const findings = blocked.flatMap((task): IntakeFinding[] =>
    task.blockers.map((blocker) => ({
      code: blocker,
      severity: "blocking",
      message: `${task.task_id} blocked by ${blocker}.`,
      task_id: task.task_id,
      evidence_refs: evidenceRefs(input.plan_path, task.task_id)
    }))
  );
  return {
    strict_task_status: merged.map((task) => ({
      ...task,
      status: input.normalized_task_ids.has(task.task_id) ? "normalized" : task.status
    })),
    fallback_task_status: merged,
    merged_task_status: merged,
    blocked_tasks: blocked,
    findings
  };
}

function statusForTask(task: ExtractedPlanTask, input: IntakeRepairMergeInput): IntakeTaskRecoveryStatus {
  const taskId = taskIdFor(task);
  const blockers: string[] = [];
  const fileClaimCount = task.explicit_file_claims.length || task.prose_file_claims.length;
  const verificationCommandCount = safeVerificationCommands(task, input).length;
  const unsafeCommandCount = task.fenced_commands.filter((command) =>
    classifyVerificationCommand({ command, workspace: input.workspace, catalog: input.catalog }).status === "unsafe"
  ).length;
  if (fileClaimCount === 0) blockers.push("missing_file_claim");
  if (verificationCommandCount === 0) blockers.push("missing_verification_for_source_mutation");
  if (unsafeCommandCount > 0) blockers.push("unsafe_verification_command");
  if (input.normalized_task_ids.has(taskId)) {
    return {
      task_id: taskId,
      title: task.title,
      status: "normalized",
      file_claim_count: fileClaimCount,
      verification_command_count: verificationCommandCount,
      blockers: []
    };
  }
  return {
    task_id: taskId,
    title: task.title,
    status: blockers.length > 0 ? "blocked" : "recovered",
    file_claim_count: fileClaimCount,
    verification_command_count: verificationCommandCount,
    blockers: [...new Set(blockers)]
  };
}

function safeVerificationCommands(task: ExtractedPlanTask, input: IntakeRepairMergeInput): string[] {
  return task.fenced_commands.filter((command) =>
    classifyVerificationCommand({ command, workspace: input.workspace, catalog: input.catalog }).status === "safe"
  );
}

function taskIdFor(task: ExtractedPlanTask): string {
  const slug = task.title.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return `task_${task.number}_${slug || "task"}`;
}

function evidenceRefs(planPath: string | null, taskId: string): string[] {
  return [planPath ? `plan:${planPath}` : "plan:inline", `plan:${taskId}`];
}
