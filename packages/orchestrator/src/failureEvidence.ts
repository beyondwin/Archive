import type { FailureClass, WorkerResult } from "@waygent/contracts";

export type FailureEvidenceKind =
  | "recoverable_patch"
  | "recoverable_worker_result"
  | "needs_operator_decision"
  | "terminal_unrecoverable";

export interface RepairBudgetSnapshot {
  max_attempts: number;
  current: number;
}

export interface FailureEvidenceInput {
  task_id: string;
  failure_class: FailureClass | string;
  worker_result?: WorkerResult | null;
  provider_attempt_ref?: string | null;
  captured_patch_ref?: string | null;
  changed_files?: string[];
  diff_scope_safe?: boolean;
  repair_budget: RepairBudgetSnapshot;
}

export type FailureEvidenceDecision =
  | {
      kind: "recoverable_patch";
      task_id: string;
      failure_class: FailureClass | string;
      patch_ref: string;
      changed_files: string[];
      evidence_refs: string[];
      recommended_action: "dispatch_repair" | "salvage_then_review";
    }
  | {
      kind: "recoverable_worker_result";
      task_id: string;
      failure_class: FailureClass | string;
      worker_result_ref: string;
      evidence_refs: string[];
      recommended_action: "dispatch_repair";
    }
  | {
      kind: "needs_operator_decision";
      task_id: string;
      failure_class: FailureClass | string;
      reason: string;
      evidence_refs: string[];
    }
  | {
      kind: "terminal_unrecoverable";
      task_id: string;
      failure_class: FailureClass | string;
      reason: string;
      evidence_refs: string[];
    };

const SALVAGE_FAILURES = new Set(["malformed_result", "adapter_crashed", "timeout"]);

export function classifyFailureEvidence(input: FailureEvidenceInput): FailureEvidenceDecision {
  const patchRef = patchRefFromInput(input);
  const evidenceRefs = evidenceRefsFor(input, patchRef);

  if (input.repair_budget.current >= input.repair_budget.max_attempts && patchRef) {
    return {
      kind: "terminal_unrecoverable",
      task_id: input.task_id,
      failure_class: input.failure_class,
      reason: "repair_budget_exhausted",
      evidence_refs: evidenceRefs
    };
  }

  if (input.failure_class === "verification_failed") {
    if (input.worker_result?.status === "completed" && patchRef) {
      return {
        kind: "recoverable_patch",
        task_id: input.task_id,
        failure_class: input.failure_class,
        patch_ref: patchRef,
        changed_files: changedFilesFrom(input),
        evidence_refs: evidenceRefs,
        recommended_action: "dispatch_repair"
      };
    }
    return decisionRequired(input, "missing_patch_evidence", evidenceRefs);
  }

  if (SALVAGE_FAILURES.has(String(input.failure_class))) {
    if (!patchRef) return decisionRequired(input, "missing_patch_evidence", evidenceRefs);
    if (input.diff_scope_safe === false) return decisionRequired(input, "unsafe_patch_scope", evidenceRefs);
    return {
      kind: "recoverable_patch",
      task_id: input.task_id,
      failure_class: input.failure_class,
      patch_ref: patchRef,
      changed_files: changedFilesFrom(input),
      evidence_refs: evidenceRefs,
      recommended_action: "salvage_then_review"
    };
  }

  return decisionRequired(input, "unsupported_failure_class", evidenceRefs);
}

function patchRefFromInput(input: FailureEvidenceInput): string | null {
  if (typeof input.captured_patch_ref === "string" && input.captured_patch_ref.length > 0) {
    return input.captured_patch_ref;
  }

  const evidence = input.worker_result?.evidence;
  const patchRef =
    evidence && typeof evidence === "object" && !Array.isArray(evidence) ? (evidence as Record<string, unknown>).patch_ref : null;
  return typeof patchRef === "string" && patchRef.length > 0 ? patchRef : null;
}

function changedFilesFrom(input: FailureEvidenceInput): string[] {
  if (input.changed_files && input.changed_files.length > 0) return [...new Set(input.changed_files)];
  return [...new Set(input.worker_result?.changed_files ?? [])];
}

function evidenceRefsFor(input: FailureEvidenceInput, patchRef: string | null): string[] {
  return [input.provider_attempt_ref ?? null, patchRef].filter(
    (ref): ref is string => typeof ref === "string" && ref.length > 0
  );
}

function decisionRequired(
  input: FailureEvidenceInput,
  reason: string,
  evidence_refs: string[]
): Extract<FailureEvidenceDecision, { kind: "needs_operator_decision" }> {
  return {
    kind: "needs_operator_decision",
    task_id: input.task_id,
    failure_class: input.failure_class,
    reason,
    evidence_refs
  };
}
