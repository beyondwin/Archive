import type { FailureClass } from "@waygent/contracts";

export interface ResumeActionInput {
  failure_class: FailureClass | string;
  retry_count: number;
  max_retries: number;
  checkpoint_ref: string | null;
}

export interface ResumeActionSelection {
  action:
    | "retry_same_provider"
    | "retry_switch_provider"
    | "rerun_verification"
    | "retry_checkpoint_generation"
    | "clean_source_checkout"
    | "human_decision";
  automatic: boolean;
}

export function selectResumeAction(input: ResumeActionInput): ResumeActionSelection {
  if (input.failure_class === "timeout" || input.failure_class === "adapter_crashed" || input.failure_class === "malformed_result") {
    return input.retry_count < input.max_retries
      ? { action: "retry_same_provider", automatic: true }
      : { action: "retry_switch_provider", automatic: false };
  }
  if (input.failure_class === "verification_failed") {
    return input.retry_count < input.max_retries
      ? { action: "rerun_verification", automatic: true }
      : { action: "human_decision", automatic: false };
  }
  if (input.failure_class === "missing_checkpoint" || input.failure_class === "artifact_missing" || input.failure_class === "state_drift") {
    return input.retry_count < input.max_retries
      ? { action: "retry_checkpoint_generation", automatic: true }
      : { action: "human_decision", automatic: false };
  }
  if (input.failure_class === "dirty_source_checkout" || input.failure_class === "needs_rebase") {
    return { action: "clean_source_checkout", automatic: false };
  }
  return { action: "human_decision", automatic: false };
}

export type RecoveryAction =
  | "retry_with_strict_prompt"
  | "retry_with_evidence"
  | "request_decision"
  | "halt";

export interface RecoveryPolicyEntry {
  action: RecoveryAction;
  max_attempts: number;
}

export interface RecoveryDecision {
  action: RecoveryAction;
  attempt_number: number;
  max_attempts: number;
  strict_prompt_suffix?: string;
}

export interface NextRecoveryOptions {
  max_overrides?: Partial<Record<FailureClass, number>>;
  prior_summary?: string;
}

const DEFAULT_POLICY: Record<FailureClass, RecoveryPolicyEntry> = {
  malformed_result: { action: "retry_with_strict_prompt", max_attempts: 2 },
  verification_failed: { action: "retry_with_evidence", max_attempts: 3 },
  timeout: { action: "request_decision", max_attempts: 1 },
  adapter_crashed: { action: "retry_with_strict_prompt", max_attempts: 1 },
  permission_denied: { action: "request_decision", max_attempts: 1 },
  cancelled: { action: "halt", max_attempts: 0 },
  diff_scope_failed: { action: "retry_with_evidence", max_attempts: 2 },
  review_changes_requested: { action: "retry_with_evidence", max_attempts: 3 },
  review_rejected: { action: "request_decision", max_attempts: 1 },
  merge_conflict: { action: "request_decision", max_attempts: 1 },
  needs_rebase: { action: "request_decision", max_attempts: 1 },
  needs_plan_fix: { action: "halt", max_attempts: 0 },
  needs_split: { action: "halt", max_attempts: 0 },
  needs_infra_fix: { action: "request_decision", max_attempts: 1 },
  missing_checkpoint: { action: "retry_with_strict_prompt", max_attempts: 1 },
  missing_resume_handler: { action: "request_decision", max_attempts: 1 },
  service_unreachable: { action: "retry_with_strict_prompt", max_attempts: 2 },
  dependency_missing: { action: "request_decision", max_attempts: 1 },
  environment_blocker: { action: "request_decision", max_attempts: 1 },
  flaky_unconfirmed: { action: "retry_with_evidence", max_attempts: 2 },
  command_not_found: { action: "request_decision", max_attempts: 1 },
  dependency_blocked: { action: "request_decision", max_attempts: 1 },
  file_claim_conflict: { action: "request_decision", max_attempts: 1 },
  dirty_source_checkout: { action: "request_decision", max_attempts: 1 },
  unsafe_apply: { action: "request_decision", max_attempts: 1 },
  state_drift: { action: "request_decision", max_attempts: 1 },
  artifact_missing: { action: "retry_with_strict_prompt", max_attempts: 1 },
  context_missing: { action: "retry_with_evidence", max_attempts: 1 },
  insufficient_context: { action: "retry_with_evidence", max_attempts: 2 },
  stale_activity: { action: "request_decision", max_attempts: 1 },
  terminal_rejected: { action: "halt", max_attempts: 0 }
};

export function recoveryPolicy(): Readonly<Record<FailureClass, RecoveryPolicyEntry>> {
  return DEFAULT_POLICY;
}

export function nextRecoveryAction(
  failure_class: FailureClass | string,
  prior_attempts: number,
  options: NextRecoveryOptions = {}
): RecoveryDecision {
  const entry = DEFAULT_POLICY[failure_class as FailureClass];
  if (!entry) {
    return { action: "request_decision", attempt_number: prior_attempts + 1, max_attempts: 1 };
  }
  const override = options.max_overrides?.[failure_class as FailureClass];
  const max_attempts = typeof override === "number" ? override : entry.max_attempts;
  const attempt_number = prior_attempts + 1;
  if (entry.action === "halt") {
    return { action: "halt", attempt_number, max_attempts };
  }
  if (prior_attempts >= max_attempts) {
    return { action: "request_decision", attempt_number, max_attempts };
  }
  if (entry.action === "retry_with_strict_prompt") {
    return {
      action: "retry_with_strict_prompt",
      attempt_number,
      max_attempts,
      strict_prompt_suffix: buildStrictPromptSuffix(failure_class, attempt_number, options.prior_summary)
    };
  }
  return { action: entry.action, attempt_number, max_attempts };
}

function buildStrictPromptSuffix(
  failure_class: FailureClass | string,
  attempt_number: number,
  prior_summary: string | undefined
): string {
  const summary = (prior_summary ?? "").slice(0, 240);
  return [
    `PRIOR ATTEMPT (#${attempt_number - 1}) FAILED.`,
    `failure_class: ${failure_class}`,
    `prior_summary: ${summary}`,
    "",
    "You MUST respond with ONLY a single fenced ```json block containing the",
    "runway.worker_result.v1 object. Required fields: schema, task_id,",
    "candidate_id, status, changed_files, summary, evidence. No prose before",
    "or after the fence. No additional fenced blocks of any language.",
    "If the prior failure was context-related, use only the task packet, evidence",
    "refs, dependency checkpoint summaries, and spec sections supplied in this retry."
  ].join("\n");
}
