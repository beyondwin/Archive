export type RiskLevel = "low" | "medium" | "high";
export type RunStatus = "pending" | "running" | "blocked" | "failed" | "completed" | "applied";
export type TaskStatus =
  | "PENDING"
  | "READY"
  | "WITHHELD_DEPENDENCY"
  | "WITHHELD_CHECKPOINT"
  | "WITHHELD_FILE_CLAIM"
  | "WITHHELD_RESOURCE_LOCK"
  | "WITHHELD_RISK"
  | "RUNNING"
  | "REVIEW"
  | "VERIFYING"
  | "FAILED_RETRYABLE"
  | "FAILED_TERMINAL"
  | "AWAITING_HUMAN_DECISION"
  | "MERGE_READY"
  | "MERGED"
  | "APPLIED";

export type EventOutcome = "success" | "failed" | "blocked" | "cancelled" | "running";
export type EventSeverity = "debug" | "info" | "warning" | "error";
export type TrustImpact =
  | "supports_success"
  | "supports_failure"
  | "neutral"
  | "requires_review"
  | "contradicts_success";

export type FailureClass =
  | "adapter_crashed"
  | "timeout"
  | "cancelled"
  | "malformed_result"
  | "diff_scope_failed"
  | "review_changes_requested"
  | "review_rejected"
  | "verification_failed"
  | "merge_conflict"
  | "needs_rebase"
  | "needs_plan_fix"
  | "needs_split"
  | "needs_infra_fix"
  | "missing_checkpoint"
  | "missing_resume_handler"
  | "stale_activity"
  | "terminal_rejected";

export interface AgentLensEvent {
  schema: "agentlens.event.v3";
  event_id: string;
  agentlens_run_id: string;
  orchestrator_run_id: string;
  producer: {
    name: string;
    kind: "orchestrator" | "kernel" | "provider" | "lens" | "policy";
    version: string;
  };
  event_type: string;
  occurred_at: string;
  sequence: number;
  phase: string;
  outcome: EventOutcome;
  severity: EventSeverity;
  trust_impact: TrustImpact;
  summary: string;
  payload: Record<string, unknown>;
  artifacts?: ArtifactReference[];
}

export interface ArtifactReference {
  artifact_id?: string;
  path: string;
  sha256: string;
  byte_length: number;
  media_type: string;
}

export interface KernelExecutionRequest {
  schema: "kernel.execution_request.v1";
  request_id: string;
  run_id: string;
  task_id: string;
  kind?: "process.exec";
  cwd: string;
  argv: string[];
  env: Record<string, string>;
  timeout_ms: number;
  stdin: "closed" | "inherit" | { text: string };
  tty: boolean;
  permission_profile?: PermissionProfile;
  capture: {
    stdout_limit_bytes: number;
    stderr_limit_bytes: number;
  };
}

export interface KernelExecutionResult {
  schema: "kernel.execution_result.v1";
  request_id: string;
  run_id: string;
  task_id: string;
  exit_code: number | null;
  signal: string | null;
  timed_out: boolean;
  stdout: string;
  stderr: string;
  stdout_truncated: boolean;
  stderr_truncated: boolean;
  stdout_sha256: string;
  stderr_sha256: string;
  changed_files: string[];
  permission_decision?: PermissionDecision;
  artifacts?: ArtifactReference[];
}

export interface WorkerResult {
  schema: "runway.worker_result.v1";
  task_id: string;
  candidate_id: string;
  status: "completed" | "failed" | "blocked";
  changed_files: string[];
  summary: string;
  evidence: Record<string, unknown>;
  failure_class?: FailureClass;
}

export interface ProviderCapabilityManifest {
  schema: "provider.capability_manifest.v1";
  provider: "fake" | "codex" | "claude" | "acp" | string;
  supported_modes: Array<"single-agent" | "multi-agent" | "review" | "verify">;
  tool_calls: boolean;
  file_edits: boolean;
  shell: boolean;
  streaming: boolean;
  approvals: boolean;
  result_schema: "runway.worker_result.v1";
}

export interface PermissionProfile {
  filesystem: {
    read: string[];
    write: string[];
    deny: string[];
  };
  network: "disabled" | "localhost" | { allow: string[] };
  command_prefixes: string[];
  escalation_reason?: string;
}

export interface PermissionDecision {
  schema: "policy.permission_decision.v1";
  allowed: boolean;
  reason: string;
  denied_by?: string;
  profile: PermissionProfile;
}

export interface DecisionPacket {
  schema: "runway.decision_packet.v1";
  task_id: string;
  failure_class: FailureClass;
  evidence_refs: string[];
  allowed_actions: string[];
  blocked_actions: string[];
  resume_input_shape: Record<string, unknown>;
  summary: string;
}
