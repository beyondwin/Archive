import type {
  AgentLensEvent,
  FailureClass,
  LensRunwayProjection,
  RunStatus,
  TrustStatus,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectApplyReadinessFromState } from "./apply";
import {
  hasActiveVerificationFailure,
  recoveredFailureRecords,
  resolveTaskVerifications
} from "./verificationResolution";

export type { TrustStatus };

export interface TrustReport {
  trust_status: TrustStatus;
  total_events: number;
  active_failure_count: number;
  recovered_failure_count: number;
  evidence_score: number;
  reasons: string[];
}

export interface FailureSummary {
  task_id: string;
  failure_class: FailureClass | "unknown";
  recovery_action: string;
  count: number;
}

export interface TimelineEntry {
  sequence: number;
  event_type: string;
  phase: string;
  outcome: string;
  summary: string;
}

export function projectTrustReport(events: AgentLensEvent[], state?: WaygentRunStateV2 | null): TrustReport {
  if (state) return projectStateTrustReport(events, state);

  const verification = events.filter((event) => event.event_type.includes("verification") && event.outcome === "success");
  const kernel = events.filter((event) => event.event_type.startsWith("kernel.") && event.outcome === "success");
  const failures = events.filter((event) => event.outcome === "failed" || event.outcome === "blocked");
  if (failures.length > 0) {
    return {
      trust_status: "failed",
      total_events: events.length,
      active_failure_count: failures.length,
      recovered_failure_count: 0,
      evidence_score: -failures.length,
      reasons: ["failure evidence present"]
    };
  }
  if (verification.length === 0 && kernel.length === 0) {
    return {
      trust_status: "insufficient_evidence",
      total_events: events.length,
      active_failure_count: 0,
      recovered_failure_count: 0,
      evidence_score: 0,
      reasons: ["verification or kernel evidence required"]
    };
  }
  return {
    trust_status: "trusted",
    total_events: events.length,
    active_failure_count: 0,
    recovered_failure_count: 0,
    evidence_score: verification.length * 2 + kernel.length,
    reasons: ["verification/kernel evidence outranks final agent claims"]
  };
}

function projectStateTrustReport(events: AgentLensEvent[], state: WaygentRunStateV2): TrustReport {
  const reasons: string[] = [];
  const activeFailures = activeFailureReasons(state, events);
  const recoveredFailures = recoveredFailureRecords(state);
  const recoveredFailureCount = Math.max(recoveredFailures.length, staleVerificationFailureTaskCount(state, events));
  const reviewNeeded = recoveredFailures.some((record) => !hasReviewEvidence(state, record.task_id));
  const verificationEvidenceCount = passedVerificationCount(state, events);
  const kernelEvidenceCount = events.filter((event) => event.event_type.startsWith("kernel.") && event.outcome === "success").length;
  const auditPassed = state.completion_audit?.status === "passed";

  if (activeFailures.length > 0) {
    return {
      trust_status: "failed",
      total_events: events.length,
      active_failure_count: activeFailures.length,
      recovered_failure_count: recoveredFailureCount,
      evidence_score: verificationEvidenceCount * 2 + kernelEvidenceCount - activeFailures.length * 3,
      reasons: unique(activeFailures)
    };
  }

  if (reviewNeeded) {
    return {
      trust_status: "needs_review",
      total_events: events.length,
      active_failure_count: 0,
      recovered_failure_count: recoveredFailureCount,
      evidence_score: verificationEvidenceCount * 2 + kernelEvidenceCount,
      reasons: ["recovered failure requires review evidence"]
    };
  }

  if (verificationEvidenceCount > 0 && auditPassed) {
    if (recoveredFailureCount > 0) reasons.push("recovered failure evidence is resolved");
    reasons.push("passed verification and completion audit evidence");
    return {
      trust_status: "trusted",
      total_events: events.length,
      active_failure_count: 0,
      recovered_failure_count: recoveredFailureCount,
      evidence_score: verificationEvidenceCount * 2 + kernelEvidenceCount + 2,
      reasons
    };
  }

  return {
    trust_status: "insufficient_evidence",
    total_events: events.length,
    active_failure_count: 0,
    recovered_failure_count: recoveredFailureCount,
    evidence_score: verificationEvidenceCount * 2 + kernelEvidenceCount,
    reasons: ["passed verification and completion audit evidence required"]
  };
}

function activeFailureReasons(state: WaygentRunStateV2, events: AgentLensEvent[]): string[] {
  const reasons: string[] = [];
  const resolutions = resolveTaskVerifications(state, events);
  const activeVerificationFailure = hasActiveVerificationFailure(state, events);
  const applyReadiness = projectApplyReadinessFromState(state);

  for (const task of Object.values(state.tasks)) {
    if (task.status !== "blocked" && task.status !== "failed") continue;
    if (task.latest_failure_class === "verification_failed" && resolutions[task.id]?.latest_status === "passed") continue;
    reasons.push("active task failure present");
  }

  if (activeVerificationFailure) reasons.push("latest verification failed");
  if (state.drift.unrepaired_blockers.length > 0) reasons.push("unrepaired drift blocker present");
  if (applyReadiness.status === "blocked" && applyReadiness.reason !== "review_evidence_missing") {
    reasons.push("active apply blocker present");
  }

  return reasons;
}

function passedVerificationCount(state: WaygentRunStateV2, events: AgentLensEvent[]): number {
  return Object.values(resolveTaskVerifications(state, events))
    .filter((resolution) => resolution.latest_status === "passed").length;
}

function staleVerificationFailureTaskCount(state: WaygentRunStateV2, events: AgentLensEvent[]): number {
  return Object.values(resolveTaskVerifications(state, events))
    .filter((resolution) => resolution.stale_failure_refs.length > 0).length;
}

function hasReviewEvidence(state: WaygentRunStateV2, taskId: string): boolean {
  const audit = state.completion_audit as { review_evidence?: unknown } | null;
  const auditEvidence = Array.isArray(audit?.review_evidence) ? audit.review_evidence : [];
  return [...auditEvidence, ...state.reviews].some((candidate) => {
    const record = objectRecord(candidate);
    if (!record) return false;
    const recordTaskId = typeof record.task_id === "string" ? record.task_id : null;
    if (recordTaskId && recordTaskId !== taskId) return false;
    const status = typeof record.status === "string"
      ? record.status
      : typeof record.outcome === "string"
        ? record.outcome
        : typeof record.verdict === "string"
          ? record.verdict
          : null;
    return status === "passed" || status === "approved" || status === "success" || status === "pass";
  });
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function unique(items: string[]): string[] {
  return Array.from(new Set(items));
}

export function projectRunwayProjection(events: AgentLensEvent[], safe_wave: string[] = []): LensRunwayProjection {
  const trust = projectTrustReport(events);
  const blocked = events.some((event) => event.outcome === "blocked");
  const failed = events.some((event) => event.outcome === "failed");
  const status: RunStatus = blocked
    ? "blocked"
    : failed
      ? "failed"
      : trust.trust_status === "trusted"
        ? "completed"
        : "running";

  return {
    schema: "lens.runway_projection.v1",
    run_id: events[0]?.orchestrator_run_id ?? "run_empty",
    status,
    safe_wave,
    trust_status: trust.trust_status,
    event_count: events.length
  };
}

export function projectFailureSummary(events: AgentLensEvent[]): FailureSummary[] {
  const grouped = new Map<string, FailureSummary>();
  for (const event of events) {
    if (event.outcome !== "failed" && event.outcome !== "blocked") continue;
    const taskId = String(event.payload.task_id ?? "task_unknown");
    const failureClass = (event.payload.failure_class ?? "unknown") as FailureSummary["failure_class"];
    const key = `${taskId}:${failureClass}`;
    const existing = grouped.get(key);
    grouped.set(key, {
      task_id: taskId,
      failure_class: failureClass,
      recovery_action: failureClass === "verification_failed" ? "retry_with_evidence" : "request_decision",
      count: (existing?.count ?? 0) + 1
    });
  }
  return [...grouped.values()];
}

export function projectTimeline(events: AgentLensEvent[]): TimelineEntry[] {
  return [...events]
    .sort((a, b) => a.sequence - b.sequence)
    .map((event) => ({
      sequence: event.sequence,
      event_type: event.event_type,
      phase: event.phase,
      outcome: event.outcome,
      summary: event.summary
    }));
}
