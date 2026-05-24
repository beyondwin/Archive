import type { WaygentTaskPacket } from "@waygent/contracts";

export interface ContextBudgetDecision {
  status: "allow" | "warn" | "block";
  failure_class: "context_missing" | null;
  shrink_actions: string[];
  summary: string;
}

export function evaluateContextBudget(packet: WaygentTaskPacket): ContextBudgetDecision {
  const budget = packet.context_budget;
  if (budget.status === "green") {
    return {
      status: "allow",
      failure_class: null,
      shrink_actions: [],
      summary: "Task packet is within context budget."
    };
  }

  const shrink_actions = budget.shrink_actions ?? defaultShrinkActions();
  if (budget.status === "yellow") {
    return {
      status: "warn",
      failure_class: null,
      shrink_actions,
      summary: "Task packet is near context budget."
    };
  }

  return {
    status: "block",
    failure_class: "context_missing",
    shrink_actions,
    summary: "Task packet exceeds context budget."
  };
}

export function defaultShrinkActions(): string[] {
  return [
    "keep_task_owned_files_and_direct_dependencies",
    "replace_full_logs_with_verification_digests",
    "replace_full_spec_with_mapped_sections",
    "summarize_prior_failures",
    "request_operator_decision_if_still_red"
  ];
}
