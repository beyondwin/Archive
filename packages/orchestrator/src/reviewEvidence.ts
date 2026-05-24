import type { WaygentRunStateV2 } from "@waygent/contracts";

export interface ReviewEvidencePolicy {
  required: boolean;
  reason: string | null;
}

export function reviewEvidencePolicy(state: WaygentRunStateV2): ReviewEvidencePolicy {
  if (state.method_evidence_required) {
    return { required: true, reason: "method_evidence_required" };
  }
  if (Object.values(state.tasks).some((task) => task.risk === "high")) {
    return { required: true, reason: "high_risk_task" };
  }
  if ((state.recovery ?? []).length > 0) {
    return { required: true, reason: "recovery_attempted" };
  }
  return { required: false, reason: null };
}

export function reviewEvidenceMissing(input: {
  state: WaygentRunStateV2;
  review_evidence: Array<Record<string, unknown>>;
}): string | null {
  const policy = reviewEvidencePolicy(input.state);
  if (!policy.required) return null;
  return input.review_evidence.length > 0 ? null : policy.reason ?? "review_required";
}
