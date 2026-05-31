import type { WaygentRunStateV2 } from "@waygent/contracts";
import { reviewEvidenceCoverage, type ReviewEvidenceArtifact, type ReviewEvidenceCoverage } from "./reviewArtifacts";

export interface ReviewEvidencePolicy {
  required: boolean;
  reason: string | null;
  reasons: string[];
  required_task_ids: string[];
  task_reasons: Record<string, string[]>;
}

export function reviewEvidencePolicy(state: WaygentRunStateV2): ReviewEvidencePolicy {
  const taskReasons = new Map<string, Set<string>>();
  const addTaskReason = (taskId: string, reason: string) => {
    taskReasons.set(taskId, new Set([...(taskReasons.get(taskId) ?? []), reason]));
  };
  const addAllTaskReason = (reason: string) => {
    for (const task of Object.values(state.tasks)) addTaskReason(task.id, reason);
  };

  if (state.method_evidence_required) {
    addAllTaskReason("method_evidence_required");
  }
  if (state.provider_profile.review_mode === "strict") {
    addAllTaskReason("strict_review_mode");
  }
  for (const task of Object.values(state.tasks)) {
    if (task.review_required) addTaskReason(task.id, "task_review_required");
    if (task.review_status && task.review_status !== "not_required" && task.review_status !== "passed") {
      addTaskReason(task.id, "task_review_pending");
    }
    if (task.evidence_policy?.require_method_evidence) addTaskReason(task.id, "method_evidence_required");
    if (task.risk === "high") addTaskReason(task.id, "high_risk_task");
    if (hasBroadFileClaim(task.file_claims)) addTaskReason(task.id, "broad_file_claim");
    if (touchesMultiplePackages(task.file_claims)) addTaskReason(task.id, "multi_package_touch");
  }
  for (const record of state.recovery ?? []) {
    const taskId = typeof record.task_id === "string" ? record.task_id : null;
    if (taskId && state.tasks[taskId]) addTaskReason(taskId, "recovery_attempted");
    else addAllTaskReason("recovery_attempted");
  }
  for (const attempt of state.provider_attempts ?? []) {
    if ((attempt.failure_class === "malformed_result" || attempt.failure_class === "adapter_crashed") && state.tasks[attempt.task_id]) {
      addTaskReason(attempt.task_id, attempt.failure_class);
    }
  }

  const task_reasons = Object.fromEntries(
    [...taskReasons.entries()].map(([taskId, reasons]) => [taskId, [...reasons]])
  );
  const reasons = [...new Set(Object.values(task_reasons).flat())];
  const reason = firstReason(reasons);
  return {
    required: reasons.length > 0,
    reason,
    reasons,
    required_task_ids: Object.keys(task_reasons),
    task_reasons
  };
}

export function reviewEvidenceMissing(input: {
  state: WaygentRunStateV2;
  review_evidence: ReviewEvidenceArtifact[];
}): string | null {
  const report = reviewEvidenceReport(input);
  if (!report.policy.required) return null;
  if (input.review_evidence.length === 0) return report.policy.reason ?? "review_required";
  if (report.coverage.failed_task_ids.length > 0) return `${report.coverage.failed_task_ids[0]}:review_failed`;
  if (report.coverage.missing_task_ids.length > 0) return `${report.coverage.missing_task_ids[0]}:missing_review_artifact`;
  return null;
}

export function reviewEvidenceReport(input: {
  state: WaygentRunStateV2;
  review_evidence: ReviewEvidenceArtifact[];
}): { policy: ReviewEvidencePolicy; coverage: ReviewEvidenceCoverage } {
  const policy = reviewEvidencePolicy(input.state);
  const coverage = reviewEvidenceCoverage({
    required_task_ids: policy.required_task_ids,
    review_evidence: input.review_evidence
  });
  return { policy, coverage };
}

function firstReason(reasons: string[]): string | null {
  const precedence = [
    "method_evidence_required",
    "strict_review_mode",
    "high_risk_task",
    "broad_file_claim",
    "recovery_attempted",
    "malformed_result",
    "adapter_crashed",
    "multi_package_touch",
    "task_review_required",
    "task_review_pending"
  ];
  return precedence.find((reason) => reasons.includes(reason)) ?? reasons[0] ?? null;
}

function hasBroadFileClaim(fileClaims: WaygentRunStateV2["tasks"][string]["file_claims"]): boolean {
  return fileClaims.some((claim) =>
    claim.mode === "owned" && (claim.path === "." || claim.path === "*" || (claim.path.split("/").length <= 1 && claim.path.endsWith("*")))
  );
}

function touchesMultiplePackages(fileClaims: WaygentRunStateV2["tasks"][string]["file_claims"]): boolean {
  const packages = new Set<string>();
  for (const claim of fileClaims) {
    if (claim.mode === "read_only") continue;
    const parts = claim.path.split("/").filter(Boolean);
    if (parts[0] === "packages" && parts[1]) packages.add(parts[1]);
  }
  return packages.size >= 2;
}
