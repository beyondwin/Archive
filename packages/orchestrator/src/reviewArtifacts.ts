import type { ReviewResult, TaskReviewArtifact } from "@waygent/contracts";

export type ReviewEvidenceArtifact = ReviewResult | TaskReviewArtifact | Record<string, unknown>;
export type NormalizedReviewRole = "spec_reviewer" | "quality_reviewer" | "combined";

export interface NormalizedReviewEvidence {
  schema: "runway.review_result.v1" | "waygent.task_review.v1";
  task_id: string;
  role: NormalizedReviewRole;
  status: "passed" | "failed" | "needs_fix";
  verdict: "approved" | "rejected";
  evidence_refs: string[];
  reviewed_patch_refs: string[];
  created_at: string | null;
  residual_risk: string[];
}

export interface ReviewEvidenceCoverage {
  required_task_ids: string[];
  passed_task_ids: string[];
  missing_task_ids: string[];
  failed_task_ids: string[];
  residual_risk: string[];
  normalized_evidence: NormalizedReviewEvidence[];
}

export function normalizeReviewEvidenceArtifact(value: ReviewEvidenceArtifact): NormalizedReviewEvidence | null {
  if (!isRecord(value)) return null;
  const schema = value.schema;
  const taskId = typeof value.task_id === "string" ? value.task_id : null;
  if (!taskId) return null;

  if (schema === "waygent.task_review.v1") {
    const role = value.role === "spec_reviewer" || value.role === "quality_reviewer" ? value.role : null;
    const status = value.status === "passed" || value.status === "failed" || value.status === "needs_fix" ? value.status : null;
    const verdict = value.verdict === "approved" || value.verdict === "rejected" ? value.verdict : null;
    if (!role || !status || !verdict) return null;
    return {
      schema,
      task_id: taskId,
      role,
      status,
      verdict,
      evidence_refs: stringArray(value.evidence_refs),
      reviewed_patch_refs: stringArray(value.reviewed_patch_refs),
      created_at: typeof value.created_at === "string" ? value.created_at : null,
      residual_risk: status === "passed" && verdict === "approved" ? [] : issueResidualRisk(value.issues)
    };
  }

  if (schema === "runway.review_result.v1" || typeof value.verdict === "string") {
    const passed = value.verdict === "pass";
    return {
      schema: "runway.review_result.v1",
      task_id: taskId,
      role: "combined",
      status: passed ? "passed" : value.verdict === "needs_fix" ? "needs_fix" : "failed",
      verdict: passed ? "approved" : "rejected",
      evidence_refs: stringArray(value.evidence_refs),
      reviewed_patch_refs: stringArray(value.reviewed_patch_refs),
      created_at: typeof value.created_at === "string" ? value.created_at : null,
      residual_risk: stringArray(value.residual_risk)
    };
  }

  return null;
}

export function reviewEvidenceCoverage(input: {
  required_task_ids: string[];
  review_evidence: ReviewEvidenceArtifact[];
}): ReviewEvidenceCoverage {
  const required = [...new Set(input.required_task_ids)];
  const normalized = input.review_evidence
    .map(normalizeReviewEvidenceArtifact)
    .filter((item): item is NormalizedReviewEvidence => item !== null);
  const byTask = new Map<string, NormalizedReviewEvidence[]>();
  for (const item of normalized) {
    byTask.set(item.task_id, [...(byTask.get(item.task_id) ?? []), item]);
  }

  const passedTaskIds: string[] = [];
  const missingTaskIds: string[] = [];
  const failedTaskIds: string[] = [];
  const residualRisk: string[] = [];

  for (const taskId of required) {
    const taskEvidence = byTask.get(taskId) ?? [];
    const latest = latestPerRole(taskEvidence);
    const failed = latest.some((item) => item.verdict !== "approved" || item.status !== "passed" || item.residual_risk.length > 0);
    if (failed) {
      failedTaskIds.push(taskId);
      residualRisk.push(`${taskId}:review_failed`);
      continue;
    }
    const hasCombined = latest.some((item) => item.role === "combined" && item.status === "passed" && item.verdict === "approved");
    const hasSpec = latest.some((item) => item.role === "spec_reviewer" && item.status === "passed" && item.verdict === "approved");
    const hasQuality = latest.some((item) => item.role === "quality_reviewer" && item.status === "passed" && item.verdict === "approved");
    if (hasCombined || (hasSpec && hasQuality)) {
      passedTaskIds.push(taskId);
      continue;
    }
    missingTaskIds.push(taskId);
    residualRisk.push(`${taskId}:missing_review_artifact`);
  }

  return {
    required_task_ids: required,
    passed_task_ids: passedTaskIds,
    missing_task_ids: missingTaskIds,
    failed_task_ids: failedTaskIds,
    residual_risk: residualRisk,
    normalized_evidence: normalized
  };
}

function latestPerRole(items: NormalizedReviewEvidence[]): NormalizedReviewEvidence[] {
  const latest = new Map<NormalizedReviewRole, NormalizedReviewEvidence>();
  for (const item of items) {
    const previous = latest.get(item.role);
    if (!previous || compareCreatedAt(previous.created_at, item.created_at) <= 0) {
      latest.set(item.role, item);
    }
  }
  return [...latest.values()];
}

function compareCreatedAt(left: string | null, right: string | null): number {
  if (left === right) return 0;
  if (!left) return -1;
  if (!right) return 1;
  return left.localeCompare(right);
}

function issueResidualRisk(value: unknown): string[] {
  if (!Array.isArray(value) || value.length === 0) return ["review_rejected"];
  return value.map((item) => {
    if (!isRecord(item)) return "review_issue";
    const severity = typeof item.severity === "string" ? item.severity : "issue";
    const summary = typeof item.summary === "string" ? item.summary : "review issue";
    return `${severity}:${summary}`;
  });
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.length > 0) : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
