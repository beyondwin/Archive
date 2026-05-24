import { existsSync } from "node:fs";
import { isAbsolute, normalize, resolve } from "node:path";
import { parseWaygentPlan, type ParsedWaygentPlan } from "./planParser";
import type { NormalizedWaygentPlan } from "./planNormalizer";
import {
  buildProjectScriptCatalog,
  type ProjectScriptCatalog
} from "./planAdapters/projectScriptCatalog";
import { commandSegments } from "./planAdapters/commandLines";
import { classifyVerificationCommand } from "./planAdapters/verificationPolicy";

export type PlanPreflightMode = "off" | "deterministic" | "full";

// Native waygent-task plans historically allowed a small set of inspect-only
// commands (`grep`, `node -e`) that the shared superpowers verification policy
// intentionally excludes. The preflight extends the shared policy with these
// legacy prefixes so already-published native plans keep validating; new
// normalized plans continue to flow only through the shared classification.
const NATIVE_TASK_EXTRA_SAFE_PREFIXES: ReadonlyArray<string> = [
  "node -e ",
  "grep "
];
const NATIVE_TASK_UNSAFE_SHELL = /\b(rm\s+-rf|git\s+reset\s+--hard|git\s+clean\s+-fd|drop\s+table|kubectl\s+delete)\b/i;

export interface PlanPreflightInput {
  workspace: string;
  plan_path: string | null;
  normalized_plan: NormalizedWaygentPlan;
  spec_path: string | null;
}

export interface PlanPreflightResult {
  status: "passed" | "failed" | "skipped";
  mode: PlanPreflightMode;
  checked_at: string;
  errors: string[];
  warnings: string[];
  task_count: number;
}

export function runPlanPreflight(input: PlanPreflightInput, mode: PlanPreflightMode = "deterministic"): PlanPreflightResult {
  if (mode === "off") {
    return {
      status: "skipped",
      mode,
      checked_at: new Date().toISOString(),
      errors: [],
      warnings: [],
      task_count: 0
    };
  }
  const errors: string[] = [];
  const warnings: string[] = [];
  let parsed: ParsedWaygentPlan | null = null;
  try {
    parsed = parseWaygentPlan(input.normalized_plan.markdown);
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
  }
  if (input.spec_path && !existsSync(input.spec_path)) {
    errors.push(`spec not found: ${input.spec_path}`);
  }
  if (parsed) {
    errors.push(...validateTasks(parsed, input.workspace));
  }
  return {
    status: errors.length > 0 ? "failed" : "passed",
    mode,
    checked_at: new Date().toISOString(),
    errors,
    warnings,
    task_count: parsed?.tasks.length ?? 0
  };
}

function validateTasks(plan: ParsedWaygentPlan, workspace: string): string[] {
  const errors: string[] = [];
  const ids = new Set(plan.tasks.map((task) => task.id));
  const catalog: ProjectScriptCatalog | null = safeBuildCatalog(workspace);
  for (const task of plan.tasks) {
    if (task.file_claims.length === 0) errors.push(`${task.id} has no explicit file claims`);
    if (task.verification_commands.length === 0) errors.push(`${task.id} has no safe verification commands`);
    for (const claim of task.file_claims) {
      if (claimEscapesWorkspace(workspace, claim.path)) errors.push(`${task.id} file claim escapes workspace: ${claim.path}`);
    }
    for (const dependency of task.dependencies) {
      if (!ids.has(dependency)) errors.push(`${task.id} depends on unknown task ${dependency}`);
    }
    for (const command of task.verification_commands) {
      const classification = classifyVerificationCommand({ command, workspace, catalog });
      if (classification.status !== "safe" && !isLegacyNativeSafeCommand(command, classification)) {
        errors.push(`${task.id} has unsafe verification command: ${command}`);
      }
    }
  }
  errors.push(...dependencyCycleErrors(plan));
  return errors;
}

function isLegacyNativeSafeCommand(
  command: string,
  classification: ReturnType<typeof classifyVerificationCommand>
): boolean {
  return commandSegments(command).every((segment, index) => {
    const classified = classification.segments[index];
    if (classified?.status === "safe") return true;
    if (classified?.reason && classified.reason !== "unknown") return false;
    if (NATIVE_TASK_UNSAFE_SHELL.test(segment) || /[|;`]/.test(segment) || /\s[12]?>/.test(segment)) {
      return false;
    }
    return NATIVE_TASK_EXTRA_SAFE_PREFIXES.some((prefix) => segment.startsWith(prefix));
  });
}

function safeBuildCatalog(workspace: string): ProjectScriptCatalog | null {
  if (!workspace) return null;
  try {
    return buildProjectScriptCatalog(workspace);
  } catch {
    return null;
  }
}

function claimEscapesWorkspace(workspace: string, claimPath: string): boolean {
  if (isAbsolute(claimPath)) return !normalize(claimPath).startsWith(normalize(workspace));
  const resolved = resolve(workspace, claimPath.replace(/\*\*.*$/, ""));
  return !resolved.startsWith(resolve(workspace));
}

function dependencyCycleErrors(plan: ParsedWaygentPlan): string[] {
  const tasks = new Map(plan.tasks.map((task) => [task.id, task]));
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const errors: string[] = [];
  const visit = (taskId: string, stack: string[]) => {
    if (visited.has(taskId)) return;
    if (visiting.has(taskId)) {
      errors.push(`dependency cycle: ${[...stack, taskId].join(" -> ")}`);
      return;
    }
    visiting.add(taskId);
    const task = tasks.get(taskId);
    for (const dependency of task?.dependencies ?? []) visit(dependency, [...stack, taskId]);
    visiting.delete(taskId);
    visited.add(taskId);
  };
  for (const task of plan.tasks) visit(task.id, []);
  return errors;
}
