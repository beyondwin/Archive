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
  | "permission_denied"
  | "service_unreachable"
  | "dependency_missing"
  | "environment_blocker"
  | "flaky_unconfirmed"
  | "command_not_found"
  | "dependency_blocked"
  | "file_claim_conflict"
  | "dirty_source_checkout"
  | "unsafe_apply"
  | "state_drift"
  | "artifact_missing"
  | "stale_activity"
  | "terminal_rejected";

export type ProviderRole = "implement" | "review" | "fix" | "verify_assist";
export type WaygentRunStatusV2 = "initializing" | "running" | "blocked" | "failed" | "completed" | "applying" | "applied";
export type WaygentLifecycleOutcome = "finished" | "blocked" | "failed" | "aborted" | null;
export type WaygentCurrentPhase = "preflight" | "dispatch" | "review" | "verify" | "recover" | "apply" | "complete";
export type WaygentTaskStatusV2 = "pending" | "ready" | "running" | "needs_fix" | "verified" | "blocked" | "failed" | "applied";

export interface WaygentFileClaim {
  path: string;
  mode: "owned" | "shared_append" | "read_only";
}

export interface WaygentTaskPacket {
  schema: "waygent.task_packet.v1";
  run_id: string;
  task_id: string;
  role: ProviderRole;
  task_title: string;
  plan_excerpt: string;
  spec_excerpt: string;
  file_claims: WaygentFileClaim[];
  allowed_write_globs: string[];
  forbidden_write_globs: string[];
  dependencies: string[];
  checkpoint_inputs: string[];
  acceptance_commands: string[];
  verification_commands: string[];
  risk: RiskLevel;
  previous_failures: Array<{ failure_class: FailureClass; evidence_refs: string[]; summary: string }>;
  decisions: Array<{ decision_id: string; summary: string }>;
  context_budget: { estimated_chars: number; max_chars: number; status: "green" | "yellow" | "red" };
  sha256: string;
}

export interface ReviewResult {
  schema: "runway.review_result.v1";
  run_id: string;
  task_id: string;
  attempt_id: string;
  provider: string;
  verdict: "pass" | "needs_fix" | "reject";
  spec_score: number;
  quality_score: number;
  findings: Array<{ severity: "critical" | "important" | "minor"; file?: string; line?: number; summary: string }>;
  residual_risk: string[];
  summary: string;
}

export interface ProviderProcessEvidence {
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  started_at: string;
  completed_at: string | null;
  event_stream?: string | null;
}

export interface ProviderAttempt {
  schema: "runway.provider_attempt.v1";
  attempt_id: string;
  run_id: string;
  task_id: string;
  role: ProviderRole;
  provider: string;
  command: string[];
  cwd: string;
  stdin_ref: string;
  stdout_ref: string;
  stderr_ref: string;
  event_stream_ref: string | null;
  exit_code: number | null;
  timed_out: boolean;
  started_at: string;
  completed_at: string | null;
  worker_result_ref: string | null;
  failure_class: FailureClass | null;
  process?: ProviderProcessEvidence;
}

export interface WaygentSourcePreflight {
  status: "clean" | "dirty_unrelated" | "dirty_related";
  dirty_files: string[];
  related: string[];
  unrelated: string[];
  checked_at: string;
  reason: string | null;
  decision_packet_ref: string | null;
}

export type ExecutionPhaseName =
  | "worktree_setup"
  | "provider"
  | "verification"
  | "checkpoint"
  | "checkpoint_dry_run"
  | "reconciliation"
  | "wave"
  | "total";

export interface ExecutionPhaseTiming {
  phase: ExecutionPhaseName;
  started: string | null;
  completed: string | null;
  duration_ms: number | null;
}

export interface ArtifactIndexEntry {
  ref: string;
  media_type: string;
  sha256: string;
  byte_length: number;
  producer_phase: ExecutionPhaseName | "task_packet" | "combined_apply" | "decision";
  task_id: string | null;
  created_at: string;
}

export interface ExecutionBarrier {
  task_id: string;
  reason: string;
  detail: string;
  wave_id: string | null;
  category: "dependency" | "checkpoint" | "file_claim" | "risk" | "failure" | "source" | "unknown";
}

export interface ExecutionCostHotspot {
  scope: "run" | "wave" | "task";
  phase: ExecutionPhaseName;
  duration_ms: number;
  task_id: string | null;
  wave_id: string | null;
}

export interface ArtifactHealthSummary {
  indexed_count: number;
  missing_count: number;
  drift_count: number;
  readiness_artifact_refs: string[];
}

export interface ExecutionExplanationProjection {
  schema: "waygent.execution_explanation.v1";
  run_id: string;
  status_summary: string;
  waves: Array<{
    wave_id: string;
    ready: string[];
    concurrency: number | null;
    duration_ms: number | null;
    withheld: Array<{ task_id: string; reason: string; detail: string | null }>;
  }>;
  barriers: ExecutionBarrier[];
  cost_hotspots: ExecutionCostHotspot[];
  artifact_health: ArtifactHealthSummary;
  recommended_next_actions: string[];
}

export interface WaygentWorktreeManifest {
  task_id: string;
  branch: string;
  path: string;
  source: string;
  source_commit: string | null;
  cleanup_status: "active" | "removed" | "failed" | "unknown";
}

export interface WaygentRunStateTaskV2 {
  id: string;
  status: WaygentTaskStatusV2;
  risk: RiskLevel;
  dependencies: string[];
  file_claims: WaygentFileClaim[];
  attempts: string[];
  task_packet_path: string | null;
  task_packet_sha256: string | null;
  unit_manifest: Record<string, unknown> | null;
  checkpoint_refs: string[];
  latest_failure_class: FailureClass | string | null;
  decision_packet_ref: string | null;
  timing: Record<string, string>;
  phase_timings?: ExecutionPhaseTiming[];
}

export interface WaygentRunStateV2 {
  schema: "waygent.run_state.v2";
  run_id: string;
  workspace: string;
  source_branch: string | null;
  worktree_root: string;
  run_root: string;
  artifact_root: string;
  state_path: string;
  event_journal_path: string;
  plan_path: string | null;
  spec_path: string | null;
  provider_profile: Record<string, unknown>;
  status: WaygentRunStatusV2;
  lifecycle_outcome: WaygentLifecycleOutcome;
  current_phase: WaygentCurrentPhase;
  preflight?: WaygentSourcePreflight;
  worktrees?: WaygentWorktreeManifest[];
  artifact_index?: ArtifactIndexEntry[];
  tasks: Record<string, WaygentRunStateTaskV2>;
  safe_waves: Array<{
    wave_id: string;
    ready: string[];
    withheld: Array<{ task_id: string; reason: string; detail?: string }>;
    concurrency?: number;
    timing?: { started: string; completed: string; duration_ms: number };
  }>;
  provider_attempts: ProviderAttempt[];
  reviews: ReviewResult[];
  verification: Array<Record<string, unknown>>;
  recovery: Array<Record<string, unknown>>;
  apply: { status: "not_applied" | "not_ready" | "blocked" | "applying" | "applied" | "failed"; reason?: string; checkpoint_ref?: string };
  context: { snapshot_path: string | null; basis_hash: string | null };
  drift: { last_checked_at: string | null; records: Array<Record<string, unknown>>; unrepaired_blockers: Array<Record<string, unknown>> };
  completion_audit: null | Record<string, unknown>;
  timestamps: { started_at: string; updated_at: string; completed_at: string | null };
}

export interface ApplyReadinessProjection {
  status: "ready" | "not_ready" | "blocked" | "applied";
  reason: string | null;
  checkpoint_refs: string[];
  combined_patch_ref: string | null;
  source: "run_state_v2" | "events";
}

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

export interface LensRunwayProjection {
  schema: "lens.runway_projection.v1";
  run_id: string;
  status: RunStatus;
  safe_wave: string[];
  trust_status: "trusted" | "failed" | "insufficient_evidence";
  event_count: number;
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
