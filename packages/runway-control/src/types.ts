import type { DecisionPacket, FailureClass, RiskLevel, TaskStatus } from "@waygent/contracts";

export type FileClaimMode = "owned" | "shared_append" | "read_only";

export interface FileClaim {
  path: string;
  mode: FileClaimMode;
}

export interface TaskNode {
  id: string;
  dependencies: string[];
  file_claims: FileClaim[];
  resource_locks: string[];
  risk: RiskLevel;
  status: TaskStatus;
  checkpoint_ref?: string;
  latest_failure_class?: FailureClass;
  stale?: boolean;
  resume_handler?: string;
  retry_count?: number;
  max_retries?: number;
}

export interface TaskGraph {
  tasks: Map<string, TaskNode>;
}

export interface WithheldTask {
  task_id: string;
  reason:
    | "dependency"
    | "checkpoint"
    | "file_claim"
    | "resource_lock"
    | "risk"
    | "failure_barrier"
    | "stale_activity";
  detail: string;
}

export interface SafeWave {
  ready: string[];
  withheld: WithheldTask[];
}

export interface DurableProjection {
  ready_tasks: string[];
  safe_wave: string[];
  withheld_tasks: WithheldTask[];
  blocked_node: string | null;
  projection_status: "ready" | "blocked" | "complete";
  next_automatic_action: string | null;
  required_human_decision: DecisionPacket | null;
}

export interface CandidateGateState {
  task_id: string;
  candidate_id: string;
  reviewed: boolean;
  verified: boolean;
  merged?: boolean;
  checkpoint_ref?: string;
  failure_class?: FailureClass;
}
