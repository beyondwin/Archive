import type { AgentLensEvent, WaygentRunStateV2 } from "@waygent/contracts";

export type ApplyReadinessReason =
  | "state_drift"
  | "review_evidence_missing"
  | "state_reconciliation_failed"
  | "terminal_invariant_failed"
  | "combined_apply_evidence_missing"
  | "checkpoint_not_apply_ready"
  | "combined_apply_patch_missing"
  | "completion_audit_failed"
  | "missing_apply_ready_evidence"
  | string;

export function applyReadinessReasonFromState(
  state: WaygentRunStateV2,
  _events?: AgentLensEvent[]
): ApplyReadinessReason {
  if (state.drift.unrepaired_blockers.length > 0) return "state_drift";

  const audit = state.completion_audit as {
    status?: string;
    residual_risk?: unknown;
    terminal_invariant?: { blockers?: Array<{ code?: string }> };
    state_reconciliation?: { passed?: boolean };
    combined_apply_evidence?: { status?: string; patch_ref?: string };
  } | null;

  if (!audit) return state.apply.reason ?? "missing_apply_ready_evidence";

  const residual = Array.isArray(audit.residual_risk) ? audit.residual_risk.map(String) : [];
  if (residual.some((item) => item.startsWith("review_evidence:"))) return "review_evidence_missing";
  if (audit.state_reconciliation && audit.state_reconciliation.passed === false) return "state_reconciliation_failed";
  if (Array.isArray(audit.terminal_invariant?.blockers) && audit.terminal_invariant.blockers.length > 0) {
    return "terminal_invariant_failed";
  }
  if (!audit.combined_apply_evidence) return "combined_apply_evidence_missing";
  if (audit.combined_apply_evidence.status !== "passed") return "checkpoint_not_apply_ready";
  if (!audit.combined_apply_evidence.patch_ref) return "combined_apply_patch_missing";
  if (audit.status !== "passed") return "completion_audit_failed";
  return state.apply.reason ?? "missing_apply_ready_evidence";
}
