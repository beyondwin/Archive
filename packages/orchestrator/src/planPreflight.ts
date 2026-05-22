import { existsSync } from "node:fs";
import { isAbsolute, normalize, resolve } from "node:path";
import { parseWaygentPlan, type ParsedWaygentPlan } from "./planParser";
import type { NormalizedWaygentPlan } from "./planNormalizer";

export type PlanPreflightMode = "off" | "deterministic" | "full";

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

const SAFE_COMMAND_STARTS = [
  "bun test",
  "bun run test",
  "bun run check",
  "bun run typecheck",
  "bun run build",
  "bun run waygent:scenarios",
  "bun run waygent:dogfood",
  "cargo test",
  "npm test",
  "npm run test",
  "node -e ",
  "pnpm test",
  "yarn test",
  "test ",
  "grep ",
  "printf ",
  "git diff --check"
];

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
      if (!isSafeVerificationCommand(command)) errors.push(`${task.id} has unsafe verification command: ${command}`);
    }
  }
  errors.push(...dependencyCycleErrors(plan));
  return errors;
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

function isSafeVerificationCommand(command: string): boolean {
  const parts = command.replace(/\s+/g, " ").trim().split(/\s+&&\s+/);
  return parts.every((part, index) => {
    if (index === 0 && part.startsWith("cd ")) return true;
    return SAFE_COMMAND_STARTS.some((prefix) => part === prefix.trim() || part.startsWith(prefix));
  });
}
