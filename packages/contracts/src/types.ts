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
  | "context_missing"
  | "insufficient_context"
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
export type ProviderLogCategory =
  | "error"
  | "warning"
  | "mcp"
  | "plugin_manifest"
  | "skill_loader"
  | "other";
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
  plan_body_truncated?: boolean;
  spec_excerpt: string;
  file_claims: WaygentFileClaim[];
  allowed_write_globs: string[];
  forbidden_write_globs: string[];
  dependencies: string[];
  checkpoint_inputs: string[];
  acceptance_commands: string[];
  verification_commands: string[];
  allowed_exec_commands?: string[] | null;
  risk: RiskLevel;
  previous_failures: Array<{ failure_class: FailureClass; evidence_refs: string[]; summary: string }>;
  decisions: Array<{ decision_id: string; summary: string }>;
  context_budget: {
    estimated_chars: number;
    max_chars: number;
    status: "green" | "yellow" | "red";
    shrink_actions?: string[];
  };
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

export interface ProviderLogSummary {
  total_lines: number;
  counts: Record<ProviderLogCategory, number>;
  samples: Array<{ category: ProviderLogCategory; line: string }>;
}

export interface ProviderProcessEvidence {
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  started_at: string;
  completed_at: string | null;
  event_stream?: string | null;
  stderr_summary?: ProviderLogSummary;
}

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  cached_read_tokens: number;
  cached_write_tokens: number;
}

export interface ModelRequest {
  model: string | null;
  reasoning: string | null;
}

export interface ModelAttestation extends ModelRequest {
  source: string;
}

export type UsageSource = "provider_json" | "event_stream" | "unknown";

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
  requested_model?: ModelRequest;
  actual_model?: ModelAttestation;
  usage?: TokenUsage | null;
  usage_source?: UsageSource;
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

export type FailureBarrierType =
  | "spec_blocker"
  | "env_blocker"
  | "ambiguity"
  | "quality_fail"
  | "verification_fail"
  | "budget_paused"
  | "checkpoint_missing"
  | "evidence_missing";

export interface FailureBarrierProjection {
  schema: "waygent.failure_barrier.v1";
  run_id: string;
  barrier_type: FailureBarrierType | null;
  task_id: string | null;
  failure_class: FailureClass | string | null;
  reason: string | null;
  evidence_refs: string[];
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

export type DogfoodEvidenceStatus = "complete" | "partial" | "missing" | "projection_error";
export type DogfoodChecklistStatus = "present" | "missing" | "stale" | "not_applicable" | "error";

export interface DogfoodEvidenceChecklistItem {
  item: string;
  status: DogfoodChecklistStatus;
  refs: string[];
  reason: string | null;
}

export interface DogfoodEvidenceProjection {
  schema: "waygent.dogfood_evidence.v1";
  run_id: string;
  status: DogfoodEvidenceStatus;
  dogfood_run_ref: string | null;
  checklist: DogfoodEvidenceChecklistItem[];
  missing_reasons: string[];
  real_runtime_timestamps: boolean;
  explain_summary: string | null;
}

export interface RuntimeCostProjection {
  schema: "waygent.runtime_cost.v1";
  run_id: string;
  estimated_wave_count: number;
  measured_wave_count: number;
  parallelism_score: number;
  serial_barriers: Array<{
    category: ExecutionBarrier["category"];
    count: number;
    task_ids: string[];
    reasons: string[];
  }>;
  phase_totals: Array<{
    phase: ExecutionPhaseName;
    duration_ms: number;
    task_ids: string[];
    wave_ids: string[];
  }>;
  top_hotspots: ExecutionCostHotspot[];
  fixed_costs: Partial<Record<ExecutionPhaseName, number>>;
  recommended_next_actions: string[];
}

export type ProviderReadinessStatus =
  | "ready"
  | "not_configured"
  | "unavailable"
  | "auth_required"
  | "failed"
  | "unknown";

export interface ProviderReadinessProjection {
  schema: "waygent.provider_readiness.v1";
  run_id: string;
  provider: string | null;
  status: ProviderReadinessStatus;
  command_summary: string[];
  stderr_summary: ProviderLogSummary | null;
  failure_class: FailureClass | string | null;
  attempt_refs: string[];
  recommended_next_action: string;
}

export interface OperationalMaturityProjection {
  schema: "waygent.operational_maturity.v1";
  run_id: string;
  hard_blocker: {
    task_id: string | null;
    failure_class: FailureClass | string;
    summary: string;
  } | null;
  dogfood_evidence: DogfoodEvidenceProjection;
  runtime_cost: RuntimeCostProjection;
  provider_readiness: ProviderReadinessProjection;
  apply_readiness: ApplyReadinessProjection;
  next_action: string;
  projection_errors: Array<{ projection: string; message: string }>;
}

export type OperatorDecisionConfidence = "deterministic" | "partial" | "unknown";
export type OperatorRunStatus =
  | "running"
  | "recovering"
  | "needs_input"
  | "needs_approval"
  | "blocked"
  | "ready_to_apply"
  | "done"
  | "failed";

export type OperatorBlockerSeverity = "info" | "warning" | "blocking" | "critical";
export type OperatorActionId =
  | "inspect_run"
  | "explain_run"
  | "open_raw_evidence"
  | "open_ai_repair_handoff"
  | "request_user_input"
  | "approve_recovery"
  | "resume_run"
  | "regenerate_checkpoint"
  | "rebase_checkpoint"
  | "rerun_verification"
  | "review_patch"
  | "apply_run";

export interface OperatorStatusSummary {
  display_status: OperatorRunStatus;
  runtime_status: WaygentRunStatusV2 | "missing" | "invalid" | "unsupported";
  lifecycle_outcome: WaygentLifecycleOutcome;
  current_phase: WaygentCurrentPhase | null;
  active_tasks: number;
  completed_tasks: number;
  blocked_tasks: number;
  apply_status: ApplyReadinessProjection["status"] | "unknown";
  summary: string;
}

export interface OperatorBlocker {
  code: string;
  title: string;
  summary: string;
  severity: OperatorBlockerSeverity;
  task_id?: string;
  evidence_refs: string[];
  missing_refs: string[];
  recommended_action_ids: OperatorActionId[];
  failure_barrier?: FailureBarrierProjection | null;
}

export interface OperatorAllowedAction {
  id: OperatorActionId;
  label: string;
  reason: string;
  evidence_refs: string[];
  requires_approval: boolean;
  requires_runtime_revalidation: boolean;
  command: string | null;
}

export interface OperatorBlockedAction {
  id: OperatorActionId;
  label: string;
  reason: string;
  evidence_refs: string[];
  unblocks_when: string;
}

export interface OperatorEvidencePacket {
  state_refs: string[];
  event_refs: string[];
  artifact_refs: string[];
  verification_refs: string[];
  checkpoint_refs: string[];
  projection_refs: string[];
  missing_refs: string[];
  redaction_notes: string[];
}

export interface OperatorAiHandoff {
  purpose: "draft_repair_plan" | "summarize_blocker" | "compare_recovery_options";
  prompt_summary: string;
  run_id: string;
  current_status: OperatorRunStatus;
  primary_blocker: string | null;
  secondary_blockers: string[];
  allowed_action_ids: OperatorActionId[];
  blocked_action_ids: OperatorActionId[];
  constraints: string[];
  evidence_refs: string[];
  missing_evidence: string[];
  raw_fallback_refs: string[];
  safety_notes: string[];
}

export interface OperatorSourceProjectionRefs {
  run_state_v2: string | null;
  apply_readiness: string | null;
  execution_explanation: string | null;
  operational_maturity: string | null;
}

export type OperatorTimelineRowType =
  | "safe_wave"
  | "task_packet"
  | "provider_attempt"
  | "worker_result"
  | "verification_result"
  | "checkpoint"
  | "review_finding"
  | "recovery_decision"
  | "apply_readiness"
  | "artifact_health"
  | "provider_readiness"
  | "raw_event";

export interface OperatorTimelineRow {
  id: string;
  sequence: number;
  timestamp: string | null;
  actor: string;
  row_type: OperatorTimelineRowType;
  title: string;
  outcome: EventOutcome | "unknown";
  severity: EventSeverity;
  task_id: string | null;
  evidence_refs: string[];
  metadata: Record<string, unknown>;
}

export interface OperatorDecisionProjection {
  schema: "waygent.operator_decision.v1";
  run_id: string;
  generated_at: string;
  status_summary: OperatorStatusSummary;
  primary_blocker: OperatorBlocker | null;
  secondary_blockers: OperatorBlocker[];
  allowed_actions: OperatorAllowedAction[];
  blocked_actions: OperatorBlockedAction[];
  evidence_packet: OperatorEvidencePacket;
  ai_handoff: OperatorAiHandoff;
  confidence: OperatorDecisionConfidence;
  unknown_reasons: string[];
  intake_recovery?: OperatorIntakeRecoverySummary;
  source_projection_refs: OperatorSourceProjectionRefs;
}

export interface WaygentWorktreeManifest {
  task_id: string;
  branch: string;
  path: string;
  source: string;
  source_commit: string | null;
  cleanup_status: "active" | "removed" | "failed" | "unknown";
}

export interface DecisionEntry {
  decision_id: string;
  task_id: string;
  decision: string;
  files: string[];
  made_at: string;
  supersedes: string | null;
}

export interface SpecManifestSection {
  id: string;
  title: string;
  range: [number, number];
  byte_offset: [number, number];
}

export interface SpecManifestTaskMapping {
  sections: string[];
  fallback_used: boolean;
  source: "explicit" | "heuristic" | "fallback";
}

export interface SpecManifest {
  spec_path: string | null;
  spec_total_chars: number;
  sections: Record<string, SpecManifestSection>;
  task_to_sections: Record<string, SpecManifestTaskMapping>;
  fallback_policy: "full_spec_on_blocker" | "halt_on_blocker";
  built_at: string;
}

export interface CostLedgerBucket {
  usage: TokenUsage;
  cost_usd: number;
  dispatches: number;
}

export interface CostLedgerTaskBucket extends CostLedgerBucket {
  last_at: string;
  model: string | null;
}

export interface CostLedger {
  by_task: Record<string, CostLedgerTaskBucket>;
  by_role: Record<string, CostLedgerBucket>;
  by_model: Record<string, CostLedgerBucket>;
  totals: TokenUsage & { cost_usd: number; dispatches: number };
  price_table_commit: string;
}

export interface TaskEvidencePolicy {
  require_method_evidence: boolean;
  verification_evidence: "required";
  method_audit_status: "missing" | "present" | "waived" | "not_required";
  waiver_reason: string | null;
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
  evidence_policy?: TaskEvidencePolicy;
  hook_retries?: number;
  model_used?: ModelAttestation[];
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
  intake_recovery?: WaygentIntakeRecovery;
  decisions_register?: DecisionEntry[];
  spec_manifest?: SpecManifest;
  cost_ledger?: CostLedger;
  budget_cap_usd?: number | null;
  budget_action?: "warn" | "pause" | "off";
  method_evidence_required?: boolean;
  hook_config?: "off" | "builtin" | string;
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

export type IntakeRecoveryStatus = "not_needed" | "recovered" | "decision_required" | "failed";
export type IntakeRecoveryConfidence = "deterministic" | "ai_assisted" | "blocked";
export type IntakeFindingSeverity = "info" | "warning" | "blocking";

export type IntakeFindingCode =
  | "task_heading_unrecognized"
  | "task_body_not_yaml"
  | "missing_frontmatter"
  | "single_spec_candidate_by_basename"
  | "file_claims_in_prose"
  | "verification_command_in_prose"
  | "verification_command_unclassified_but_safe"
  | "plan_section_body_sparse_but_spec_section_available"
  | "multiple_plan_or_spec_candidates"
  | "destructive_command_candidate"
  | "unsafe_verification_command"
  | "verification_claim_mismatch"
  | "missing_file_claim"
  | "adjacent_contract_candidate"
  | "conflicting_owned_claim"
  | "path_escape"
  | "missing_verification_for_source_mutation"
  | "external_credentials_required"
  | "scope_expansion"
  | "apply_without_verification_evidence";

export interface IntakeFinding {
  code: IntakeFindingCode | string;
  severity: IntakeFindingSeverity;
  message: string;
  task_id: string | null;
  evidence_refs: string[];
}

export interface IntakeRepairAction {
  action: string;
  status: "applied" | "blocked" | "skipped";
  reason: string;
  evidence_refs: string[];
}

export type IntakeTaskStatus = "normalized" | "recovered" | "blocked" | "warning";

export interface IntakeTaskRecoveryStatus {
  task_id: string;
  status: IntakeTaskStatus;
  title: string;
  file_claim_count: number;
  verification_command_count: number;
  blockers: string[];
}

export interface WaygentIntakeRecovery {
  status: IntakeRecoveryStatus;
  started_at: string;
  completed_at: string;
  normalized_plan_ref: string | null;
  recovery_report_ref: string | null;
  findings: IntakeFinding[];
  repair_actions: IntakeRepairAction[];
  can_start: boolean;
  confidence: IntakeRecoveryConfidence;
  question: string | null;
  strict_task_status?: IntakeTaskRecoveryStatus[];
  fallback_task_status?: IntakeTaskRecoveryStatus[];
  merged_task_status?: IntakeTaskRecoveryStatus[];
  blocked_tasks?: IntakeTaskRecoveryStatus[];
  extract_report_ref?: string | null;
}

export interface OperatorIntakeRecoverySummary {
  status: IntakeRecoveryStatus;
  can_start: boolean;
  confidence: IntakeRecoveryConfidence;
  finding_codes: string[];
  artifact_refs: string[];
  question: string | null;
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
