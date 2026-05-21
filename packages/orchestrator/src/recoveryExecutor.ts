import type { FailureClass } from "@waygent/contracts";

export interface ResumeActionInput {
  failure_class: FailureClass | string;
  retry_count: number;
  max_retries: number;
  checkpoint_ref: string | null;
}

export interface ResumeActionSelection {
  action: "retry_same_provider" | "retry_switch_provider" | "rerun_verification" | "human_decision";
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
  return { action: "human_decision", automatic: false };
}
