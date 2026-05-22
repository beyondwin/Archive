import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { TaskEvidencePolicy, WaygentRunStateV2 } from "@waygent/contracts";

export interface MethodEvidenceValidationInput {
  state: WaygentRunStateV2;
  require_method_evidence: boolean;
}

export interface MethodEvidenceValidationResult {
  status: "passed" | "blocked";
  reason: string | null;
  missing_task_ids: string[];
  policies: Record<string, TaskEvidencePolicy>;
}

const WAIVER_REASONS = new Set(["docs_only", "config_only", "generated_only"]);

export function validateMethodEvidenceForApply(input: MethodEvidenceValidationInput): MethodEvidenceValidationResult {
  const policies: Record<string, TaskEvidencePolicy> = {};
  if (!input.require_method_evidence) {
    return { status: "passed", reason: null, missing_task_ids: [], policies };
  }
  const missing: string[] = [];
  for (const task of Object.values(input.state.tasks)) {
    if (task.status !== "verified" && task.status !== "applied") continue;
    const methodAudit = methodAuditForTask(input.state, task.id);
    const waiver = methodAudit && typeof methodAudit.waiver === "string" ? methodAudit.waiver : null;
    const waiverAllowed = waiver ? WAIVER_REASONS.has(waiver) : docsOrConfigOnly(task.file_claims.map((claim) => claim.path));
    const present = methodAuditPresent(methodAudit);
    const policy: TaskEvidencePolicy = {
      require_method_evidence: true,
      verification_evidence: "required",
      method_audit_status: present ? "present" : waiverAllowed ? "waived" : "missing",
      waiver_reason: present ? null : waiverAllowed ? waiver ?? inferredWaiver(task.file_claims.map((claim) => claim.path)) : null
    };
    policies[task.id] = policy;
    if (policy.method_audit_status === "missing") missing.push(task.id);
  }
  return {
    status: missing.length > 0 ? "blocked" : "passed",
    reason: missing.length > 0 ? "method_evidence_missing" : null,
    missing_task_ids: missing,
    policies
  };
}

function methodAuditForTask(state: WaygentRunStateV2, taskId: string): Record<string, unknown> | null {
  for (const attempt of state.provider_attempts.filter((candidate) => candidate.task_id === taskId).reverse()) {
    if (!attempt.worker_result_ref) continue;
    const path = join(state.run_root, attempt.worker_result_ref);
    if (!existsSync(path)) continue;
    try {
      const parsed = JSON.parse(readFileSync(path, "utf8")) as { evidence?: Record<string, unknown> };
      const audit = parsed.evidence?.method_audit;
      return audit && typeof audit === "object" && !Array.isArray(audit) ? audit as Record<string, unknown> : null;
    } catch {
      return null;
    }
  }
  return null;
}

function methodAuditPresent(audit: Record<string, unknown> | null): boolean {
  if (!audit) return false;
  return Boolean(audit.tdd || audit.review || audit.verification);
}

function docsOrConfigOnly(paths: string[]): boolean {
  return paths.length > 0 && paths.every((path) =>
    path.startsWith("docs/") ||
    path.endsWith(".md") ||
    path.endsWith(".mdx") ||
    path.endsWith(".json") ||
    path.endsWith(".yml") ||
    path.endsWith(".yaml") ||
    path.includes("generated")
  );
}

function inferredWaiver(paths: string[]): string | null {
  if (paths.every((path) => path.startsWith("docs/") || path.endsWith(".md") || path.endsWith(".mdx"))) return "docs_only";
  if (paths.every((path) => path.endsWith(".json") || path.endsWith(".yml") || path.endsWith(".yaml"))) return "config_only";
  if (paths.every((path) => path.includes("generated"))) return "generated_only";
  return null;
}
