import type { FailureClass, WaygentRunStateV2 } from "@waygent/contracts";
import { nextRecoveryAction } from "./recoveryExecutor";
import type { ScopeFailureKind } from "./diffScope";

export interface SchedulerRecoveryInput {
  state: WaygentRunStateV2;
  task_id: string;
  failure_class: FailureClass | string;
  prior_summary: string;
  evidence_refs: string[];
  scope_failure_kind?: ScopeFailureKind;
  recommended_scope_amendments?: Array<{
    path: string;
    mode: "owned";
    reason: string;
    evidence_refs: string[];
  }>;
}

export function priorRecoveryAttempts(
  state: WaygentRunStateV2,
  task_id: string,
  failure_class: FailureClass | string
): number {
  return (state.recovery ?? []).filter((record) =>
    record.task_id === task_id && record.failure_class === failure_class
  ).length;
}

export function appendSchedulerRecovery(input: SchedulerRecoveryInput) {
  const prior = priorRecoveryAttempts(input.state, input.task_id, input.failure_class);
  const decision = nextRecoveryAction(input.failure_class, prior, {
    prior_summary: input.prior_summary,
    ...(input.scope_failure_kind ? { scope_failure_kind: input.scope_failure_kind } : {})
  });
  const record = {
    task_id: input.task_id,
    failure_class: input.failure_class,
    ...(input.scope_failure_kind ? { scope_failure_kind: input.scope_failure_kind } : {}),
    ...(input.recommended_scope_amendments ? { recommended_scope_amendments: input.recommended_scope_amendments } : {}),
    action: decision.action,
    attempt_number: decision.attempt_number,
    max_attempts: decision.max_attempts,
    automatic: decision.action !== "request_decision" && decision.action !== "halt",
    prior_summary: input.prior_summary,
    result: decision.action === "request_decision" || decision.action === "halt" ? "blocked" : "scheduled",
    evidence_refs: input.evidence_refs
  };
  input.state.recovery.push(record);
  return { decision, record };
}
