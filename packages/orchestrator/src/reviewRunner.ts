import { existsSync, readFileSync } from "node:fs";
import type { ArtifactReference, FailureClass, TaskReviewArtifact, TaskReviewStatus, WaygentRunStateV2 } from "@waygent/contracts";
import { appendEvent, runPaths, writeArtifact } from "@waygent/lens-store";
import { artifactIndexEntry, mergeArtifactIndex } from "./artifactIndex";
import { resolveCheckpointPatch } from "./checkpointArtifacts";
import { buildCompletionAudit } from "./completionAudit";
import { normalizeReviewEvidenceArtifact } from "./reviewArtifacts";
import { reviewEvidencePolicy } from "./reviewEvidence";
import { buildReviewPacket, type ReviewRole } from "./reviewPacket";
import { nextRunEvent } from "./runEvents";
import { readRunStateV2Result, writeRunStateV2, type RunStateV2ReadResult } from "./runState";
import { taskRequiresCheckpoint } from "./taskCheckpointPolicy";

export interface ReviewRunOptions {
  root: string;
  run: string;
  task?: string;
  role?: ReviewRole;
}

export interface ReviewRunResult {
  command: "review";
  run_id: string;
  status: "passed" | "failed" | "blocked";
  review_refs: string[];
  review_packet_refs: string[];
  total_reviews: number;
  task_id?: string;
  role?: ReviewRole;
  reason?: string;
  failure_class?: FailureClass | string | null;
}

export function reviewRun(options: ReviewRunOptions): ReviewRunResult {
  const stateResult = readRunStateV2Result(options.root, options.run);
  if (stateResult.status !== "ok") return blockedReviewResult(options.run, stateBlocker(stateResult), options.task, options.role);
  if (budgetPaused(stateResult.state)) return blockedReviewResult(options.run, "budget_paused", options.task, options.role, "cost_budget_exhausted");

  const selection = selectReviewTasks(stateResult.state, options.task);
  if (selection.tasks.length === 0) {
    const reason = selection.reason ?? "no_review_required";
    if (reason === "no_review_required") {
      return {
        command: "review",
        run_id: options.run,
        status: "passed",
        review_refs: [],
        review_packet_refs: [],
        total_reviews: 0,
        ...(options.task ? { task_id: options.task } : {}),
        ...(options.role ? { role: options.role } : {}),
        reason
      };
    }
    return blockedReviewResult(options.run, reason, options.task, options.role);
  }

  let state = stateResult.state;
  const reviewRefs: string[] = [];
  const reviewPacketRefs: string[] = [];
  let sawFailure = false;
  let failureClass: FailureClass | string | null = null;

  for (const task of selection.tasks) {
    const roles = options.role ? [options.role] : missingReviewRoles(state, task.id);
    for (const role of roles) {
      const currentTask = state.tasks[task.id];
      if (!currentTask) continue;
      const reviewedAt = new Date().toISOString();
      const reviewId = nextReviewId(state, currentTask.id, role);
      const taskPacket = readTaskPacket(currentTask.task_packet_path);
      const packet = buildReviewPacket({
        state,
        task: currentTask,
        role,
        review_id: reviewId,
        task_packet: taskPacket,
        verification_refs: taskVerificationRefs(state, currentTask.id),
        worker_result_refs: taskWorkerResultRefs(state, currentTask.id),
        prior_review_refs: currentTask.review_refs ?? [],
        reviewed_patch_refs: taskReviewedPatchRefs(state, currentTask)
      });
      const paths = runPaths(options.root, options.run);
      const packetArtifact = writeArtifact(paths.root, `task_packets/review_${currentTask.id}_${role}.json`, `${JSON.stringify(packet, null, 2)}\n`);
      const artifact = buildDeterministicReviewArtifact({
        state,
        task: currentTask,
        role,
        review_id: reviewId,
        created_at: reviewedAt,
        evidence_refs: [packetArtifact.path, ...packet.verification_refs, ...packet.worker_result_refs],
        reviewed_patch_refs: packet.reviewed_patch_refs
      });
      const reviewArtifact = writeArtifact(paths.root, `reviews/${currentTask.id}/${reviewId}.json`, `${JSON.stringify(artifact, null, 2)}\n`);
      const passed = artifact.status === "passed" && artifact.verdict === "approved";
      reviewRefs.push(reviewArtifact.path);
      reviewPacketRefs.push(packetArtifact.path);
      sawFailure ||= !passed;
      failureClass = passed ? failureClass : "review_changes_requested";

      state = applyReviewToState({
        state,
        task_id: currentTask.id,
        role,
        review: artifact,
        review_artifact: reviewArtifact,
        packet_artifact: packetArtifact,
        created_at: reviewedAt
      });
      writeRunStateV2(options.root, state);
      appendEvent(paths.events, nextRunEvent(paths.events, {
        run_id: options.run,
        event_type: "runway.review_result",
        phase: "review",
        outcome: passed ? "success" : "failed",
        summary: passed ? "Manual review artifact approved the task." : "Manual review artifact requested fixes.",
        payload: {
          task_id: currentTask.id,
          role,
          verdict: artifact.verdict,
          status: artifact.status,
          review_ref: reviewArtifact.path,
          review_packet_ref: packetArtifact.path
        },
        trust_impact: passed ? "supports_success" : "supports_failure"
      }));
    }
  }

  return {
    command: "review",
    run_id: options.run,
    status: sawFailure ? "failed" : "passed",
    review_refs: reviewRefs,
    review_packet_refs: reviewPacketRefs,
    total_reviews: reviewRefs.length,
    ...(options.task ? { task_id: options.task } : {}),
    ...(options.role ? { role: options.role } : {}),
    failure_class: failureClass
  };
}

function blockedReviewResult(
  runId: string,
  reason: string,
  taskId?: string,
  role?: ReviewRole,
  failureClass?: FailureClass | string | null
): ReviewRunResult {
  return {
    command: "review",
    run_id: runId,
    status: "blocked",
    reason,
    review_refs: [],
    review_packet_refs: [],
    total_reviews: 0,
    ...(taskId ? { task_id: taskId } : {}),
    ...(role ? { role } : {}),
    ...(failureClass ? { failure_class: failureClass } : {})
  };
}

function stateBlocker(result: Exclude<RunStateV2ReadResult, { status: "ok" }>): string {
  return result.reason;
}

function selectReviewTasks(state: WaygentRunStateV2, taskId?: string): {
  tasks: WaygentRunStateV2["tasks"][string][];
  reason?: string;
} {
  if (taskId) {
    const task = state.tasks[taskId];
    return task ? { tasks: [task] } : { tasks: [], reason: "unknown_task" };
  }
  const policy = reviewEvidencePolicy(state);
  if (!policy.required) return { tasks: [], reason: "no_review_required" };
  const tasks = policy.required_task_ids
    .map((id) => state.tasks[id])
    .filter((task): task is WaygentRunStateV2["tasks"][string] => Boolean(task));
  return tasks.length > 0 ? { tasks } : { tasks: [], reason: "no_review_required" };
}

function missingReviewRoles(state: WaygentRunStateV2, taskId: string): ReviewRole[] {
  const normalized = state.reviews
    .map(normalizeReviewEvidenceArtifact)
    .filter((item) => item?.task_id === taskId);
  if (normalized.some((item) => item?.role === "combined" && item.status === "passed" && item.verdict === "approved")) return [];
  const passedRoles = new Set(normalized
    .filter((item) => item?.status === "passed" && item.verdict === "approved")
    .map((item) => item?.role));
  const roles: ReviewRole[] = [];
  if (!passedRoles.has("spec_reviewer")) roles.push("spec_reviewer");
  if (!passedRoles.has("quality_reviewer")) roles.push("quality_reviewer");
  return roles;
}

function nextReviewId(state: WaygentRunStateV2, taskId: string, role: ReviewRole): string {
  const count = state.reviews.filter((review) => review.task_id === taskId).length + 1;
  return `review_${taskId}_${role}_${count}`;
}

function readTaskPacket(path: string | null): Record<string, unknown> | null {
  if (!path || !existsSync(path)) return null;
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as unknown;
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function taskVerificationRefs(state: WaygentRunStateV2, taskId: string): string[] {
  return state.verification
    .filter((record) => record.task_id === taskId)
    .map((record) => record.kernel_result_ref)
    .filter((ref): ref is string => typeof ref === "string" && ref.length > 0);
}

function taskWorkerResultRefs(state: WaygentRunStateV2, taskId: string): string[] {
  return state.provider_attempts
    .filter((attempt) => attempt.task_id === taskId)
    .map((attempt) => attempt.worker_result_ref)
    .filter((ref): ref is string => typeof ref === "string" && ref.length > 0);
}

function taskReviewedPatchRefs(state: WaygentRunStateV2, task: WaygentRunStateV2["tasks"][string]): string[] {
  return task.checkpoint_refs.map((checkpointRef) => {
    const resolved = resolveCheckpointPatch(state.run_root, checkpointRef);
    return resolved?.manifest.patch_ref ?? checkpointRef;
  });
}

function buildDeterministicReviewArtifact(input: {
  state: WaygentRunStateV2;
  task: WaygentRunStateV2["tasks"][string];
  role: ReviewRole;
  review_id: string;
  created_at: string;
  evidence_refs: string[];
  reviewed_patch_refs: string[];
}): TaskReviewArtifact {
  const missingPatch = taskRequiresCheckpoint(input.task) && input.reviewed_patch_refs.length === 0;
  const issues = missingPatch
    ? [{
      severity: "important" as const,
      summary: "Review could not find an apply-ready patch or checkpoint for this task.",
      required_fix: "Generate checkpoint evidence before approving review."
    }]
    : [];
  const model = reviewModel(input.state);
  return {
    schema: "waygent.task_review.v1",
    run_id: input.state.run_id,
    task_id: input.task.id,
    review_id: input.review_id,
    role: input.role,
    status: issues.length > 0 ? "needs_fix" : "passed",
    verdict: issues.length > 0 ? "rejected" : "approved",
    issues,
    evidence_refs: input.evidence_refs,
    reviewed_patch_refs: input.reviewed_patch_refs,
    ...(model ? { model } : {}),
    created_at: input.created_at
  };
}

function reviewModel(state: WaygentRunStateV2): string | null {
  const roles = state.provider_profile.roles;
  if (typeof roles !== "object" || roles === null || Array.isArray(roles)) return null;
  const review = (roles as Record<string, unknown>).review;
  if (typeof review !== "object" || review === null || Array.isArray(review)) return null;
  const model = (review as Record<string, unknown>).model;
  return typeof model === "string" && model.length > 0 ? model : null;
}

function applyReviewToState(input: {
  state: WaygentRunStateV2;
  task_id: string;
  role: ReviewRole;
  review: TaskReviewArtifact;
  review_artifact: ArtifactReference;
  packet_artifact: ArtifactReference;
  created_at: string;
}): WaygentRunStateV2 {
  const task = input.state.tasks[input.task_id]!;
  const passed = input.review.status === "passed" && input.review.verdict === "approved";
  const reviewRefs = [...new Set([...(task.review_refs ?? []), input.review_artifact.path])];
  const nextReviews = [...input.state.reviews, input.review];
  const nextTask = {
    ...task,
    review_required: true,
    review_refs: reviewRefs,
    review_status: passed ? nextTaskReviewStatus(nextReviews, input.task_id) : "failed" as const,
    status: nextTaskStatus(task.status, input.role, passed, task.checkpoint_refs.length > 0),
    latest_failure_class: passed ? task.latest_failure_class : "review_changes_requested",
    timing: { ...task.timing, [`${input.role}_reviewed_at`]: input.created_at }
  };
  const nextState: WaygentRunStateV2 = {
    ...input.state,
    tasks: { ...input.state.tasks, [input.task_id]: nextTask },
    reviews: nextReviews,
    artifact_index: mergeArtifactIndex(input.state.artifact_index, [
      artifactIndexEntry({
        artifact: input.packet_artifact,
        producer_phase: "task_packet",
        task_id: input.task_id,
        created_at: input.created_at
      }),
      artifactIndexEntry({
        artifact: input.review_artifact,
        producer_phase: "decision",
        task_id: input.task_id,
        created_at: input.created_at
      })
    ]),
    status: passed ? input.state.status : "blocked",
    lifecycle_outcome: passed ? input.state.lifecycle_outcome : "blocked",
    current_phase: passed ? "review" : "recover",
    timestamps: {
      ...input.state.timestamps,
      updated_at: input.created_at
    }
  };
  return {
    ...nextState,
    completion_audit: refreshReviewCompletionAudit(nextState)
  };
}

function nextTaskReviewStatus(reviews: WaygentRunStateV2["reviews"], taskId: string): TaskReviewStatus {
  const normalized = reviews
    .map(normalizeReviewEvidenceArtifact)
    .filter((item) => item?.task_id === taskId);
  const hasCombined = normalized.some((item) => item?.role === "combined" && item.status === "passed" && item.verdict === "approved");
  const hasSpec = normalized.some((item) => item?.role === "spec_reviewer" && item.status === "passed" && item.verdict === "approved");
  const hasQuality = normalized.some((item) => item?.role === "quality_reviewer" && item.status === "passed" && item.verdict === "approved");
  return hasCombined || (hasSpec && hasQuality) ? "passed" : "pending";
}

function nextTaskStatus(
  current: WaygentRunStateV2["tasks"][string]["status"],
  role: ReviewRole,
  passed: boolean,
  hasCheckpoint: boolean
): WaygentRunStateV2["tasks"][string]["status"] {
  if (!passed) return role === "spec_reviewer" ? "spec_review_failed" : "quality_review_failed";
  if (current === "verified" || current === "applied") return current;
  if (role === "spec_reviewer") return "spec_review_passed";
  return hasCheckpoint ? "checkpoint_ready" : "review_passed";
}

function refreshReviewCompletionAudit(state: WaygentRunStateV2): WaygentRunStateV2["completion_audit"] {
  const previous = state.completion_audit;
  if (!previous || typeof previous !== "object" || Array.isArray(previous)) return previous;
  const requiredChecks = stringArray(previous.required_checks);
  const checklist = stringArray(previous.prompt_to_artifact_checklist);
  const auditInput: Parameters<typeof buildCompletionAudit>[0] = {
    state,
    required_checks: requiredChecks,
    verification_evidence: state.verification,
    review_evidence: state.reviews,
    prompt_to_artifact_checklist: checklist
  };
  if (previous.combined_apply_evidence) {
    auditInput.combined_apply_evidence = previous.combined_apply_evidence as NonNullable<Parameters<typeof buildCompletionAudit>[0]["combined_apply_evidence"]>;
  }
  return buildCompletionAudit(auditInput);
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.length > 0) : [];
}

function budgetPaused(state: WaygentRunStateV2): boolean {
  if (state.apply.reason === "budget_paused") return true;
  if (
    state.budget_action === "pause" &&
    typeof state.budget_cap_usd === "number" &&
    typeof state.cost_ledger?.totals.cost_usd === "number" &&
    state.cost_ledger.totals.cost_usd > state.budget_cap_usd
  ) {
    return true;
  }
  return (state.recovery ?? []).some((record) =>
    record.reason === "budget_paused" || record.failure_class === "budget_paused"
  );
}
