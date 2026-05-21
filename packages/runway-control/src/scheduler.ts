import type { DecisionPacket, FailureClass } from "@waygent/contracts";
import type { FileClaim, SafeWave, TaskGraph, TaskNode, WithheldTask } from "./types";

export function createTaskGraph(tasks: TaskNode[]): TaskGraph {
  const graph = { tasks: new Map(tasks.map((task) => [task.id, { ...task }])) };
  for (const task of graph.tasks.values()) {
    for (const dependency of task.dependencies) {
      if (!graph.tasks.has(dependency)) {
        throw new Error(`${task.id} depends on unknown task ${dependency}`);
      }
    }
  }
  assertAcyclic(graph);
  return graph;
}

export function assertAcyclic(graph: TaskGraph): void {
  const visiting = new Set<string>();
  const visited = new Set<string>();

  const visit = (taskId: string): void => {
    if (visited.has(taskId)) return;
    if (visiting.has(taskId)) throw new Error(`cycle detected at ${taskId}`);
    visiting.add(taskId);
    for (const dependency of graph.tasks.get(taskId)?.dependencies ?? []) visit(dependency);
    visiting.delete(taskId);
    visited.add(taskId);
  };

  for (const taskId of graph.tasks.keys()) visit(taskId);
}

export function computeSafeWave(graph: TaskGraph): SafeWave {
  const withheld: WithheldTask[] = [];
  const candidates = [...graph.tasks.values()].filter((task) => {
    if (task.status !== "READY" && task.status !== "PENDING") return false;
    const barrier = barrierFor(task, graph);
    if (barrier) {
      withheld.push(barrier);
      return false;
    }
    return true;
  });

  const ready: string[] = [];
  for (const task of candidates) {
    const conflict = ready
      .map((id) => graph.tasks.get(id))
      .find((other): other is TaskNode => other !== undefined && claimsConflict(task.file_claims, other.file_claims));
    if (conflict) {
      withheld.push({
        task_id: task.id,
        reason: "file_claim",
        detail: `${task.id} conflicts with ${conflict.id}`
      });
      continue;
    }
    if (task.risk === "high" && ready.length > 0) {
      withheld.push({ task_id: task.id, reason: "risk", detail: "high risk tasks serialize" });
      continue;
    }
    if (ready.some((id) => graph.tasks.get(id)?.risk === "high")) {
      withheld.push({ task_id: task.id, reason: "risk", detail: "safe wave already contains high risk task" });
      continue;
    }
    ready.push(task.id);
  }

  return { ready, withheld };
}

export function barrierFor(task: TaskNode, graph: TaskGraph): WithheldTask | null {
  if (task.stale) return { task_id: task.id, reason: "stale_activity", detail: "task has stale activity" };
  if (task.latest_failure_class === "missing_resume_handler" && !task.resume_handler) {
    return { task_id: task.id, reason: "failure_barrier", detail: "missing resume handler" };
  }
  if (task.latest_failure_class && terminalFailures.has(task.latest_failure_class)) {
    return { task_id: task.id, reason: "failure_barrier", detail: task.latest_failure_class };
  }
  for (const dependency of task.dependencies) {
    const dep = graph.tasks.get(dependency);
    if (!dep) return { task_id: task.id, reason: "dependency", detail: `${dependency} is missing` };
    if (!dep.checkpoint_ref) {
      return { task_id: task.id, reason: "checkpoint", detail: `${dependency} has no checkpoint` };
    }
  }
  return null;
}

export function claimsConflict(left: FileClaim[], right: FileClaim[]): boolean {
  for (const a of left) {
    for (const b of right) {
      if (a.mode === "read_only" || b.mode === "read_only") continue;
      if (a.mode === "shared_append" && b.mode === "shared_append") continue;
      if (samePathFamily(a.path, b.path)) return true;
    }
  }
  return false;
}

function samePathFamily(left: string, right: string): boolean {
  const a = left.replace(/\/+$/, "");
  const b = right.replace(/\/+$/, "");
  return a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`);
}

const terminalFailures = new Set<FailureClass>([
  "terminal_rejected",
  "review_rejected",
  "needs_plan_fix",
  "needs_split",
  "missing_checkpoint"
]);

export function retryRecommendation(task: TaskNode): "retry" | "human_decision" {
  const retryCount = task.retry_count ?? 0;
  const maxRetries = task.max_retries ?? 1;
  if (task.latest_failure_class && terminalFailures.has(task.latest_failure_class)) return "human_decision";
  return retryCount < maxRetries ? "retry" : "human_decision";
}

export function createDecisionPacket(task: TaskNode, evidence_refs: string[] = []): DecisionPacket {
  const failure = task.latest_failure_class ?? "needs_infra_fix";
  return {
    schema: "runway.decision_packet.v1",
    task_id: task.id,
    failure_class: failure,
    evidence_refs,
    allowed_actions: ["retry_from_checkpoint", "split_task", "mark_terminal", "edit_plan"],
    blocked_actions: ["create_mutable_worktree_without_safe_wave", "apply_without_verification"],
    resume_input_shape: {
      action: "retry_from_checkpoint|split_task|mark_terminal|edit_plan",
      checkpoint_ref: task.checkpoint_ref ?? null,
      reason: "string"
    },
    summary: `${task.id} is blocked by ${failure}`
  };
}

export function canCreateMutableWorktree(task: TaskNode, safeWave: string[]): boolean {
  return safeWave.includes(task.id);
}
