import { createTaskGraph, type TaskGraph, type TaskNode } from "@waygent/runway-control";
import type { ParsedWaygentPlan } from "./planParser";

export function buildTaskGraphFromPlan(plan: ParsedWaygentPlan): TaskGraph {
  const nodes: TaskNode[] = plan.tasks.map((task) => ({
    id: task.id,
    dependencies: task.dependencies,
    file_claims: task.file_claims,
    resource_locks: [],
    risk: task.risk,
    status: task.dependencies.length === 0 ? "READY" : "PENDING"
  }));
  return createTaskGraph(nodes);
}
