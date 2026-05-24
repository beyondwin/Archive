import type { ParsedWaygentPlan, ParsedWaygentTask } from "./planParser";

export interface ExecutionDependencyBarrier {
  task_id: string;
  depends_on: string[];
  reason: "broad_gradle_verification" | "module_overlap";
  detail: string;
}

export interface ExecutionDependencyBarrierResult {
  plan: ParsedWaygentPlan;
  barriers: ExecutionDependencyBarrier[];
}

export function applyExecutionDependencyBarriers(plan: ParsedWaygentPlan): ExecutionDependencyBarrierResult {
  const barriers: ExecutionDependencyBarrier[] = [];
  const tasks = plan.tasks.map((task) => ({ ...task, dependencies: [...task.dependencies] }));
  for (const [index, task] of tasks.entries()) {
    if (!hasBroadGradleVerification(task)) continue;
    const previousModuleTasks = tasks
      .slice(0, index)
      .filter((candidate) => claimedModules(candidate).length > 0)
      .map((candidate) => candidate.id);
    const missingDeps = previousModuleTasks.filter((id) => !task.dependencies.includes(id));
    if (missingDeps.length === 0) continue;
    task.dependencies.push(...missingDeps);
    barriers.push({
      task_id: task.id,
      depends_on: missingDeps,
      reason: "broad_gradle_verification",
      detail: `${task.verification_commands.find((command) => command.includes("gradle"))} reads modules touched by earlier tasks`
    });
  }
  return { plan: { tasks }, barriers };
}

function hasBroadGradleVerification(task: ParsedWaygentTask): boolean {
  return task.verification_commands.some((command) => {
    const normalized = command.replace(/\s+/g, " ").trim();
    return normalized === "./gradlew test" ||
      normalized === "gradle test" ||
      normalized === "./gradlew check" ||
      normalized === "gradle check" ||
      normalized === "./gradlew build" ||
      normalized === "gradle build";
  });
}

function claimedModules(task: ParsedWaygentTask): string[] {
  const modules = new Set<string>();
  for (const claim of task.file_claims) {
    const first = claim.path.split("/")[0];
    if (first && first.startsWith("fixthis-")) modules.add(first);
  }
  return [...modules];
}
