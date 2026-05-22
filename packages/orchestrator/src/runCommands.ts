import { readdirSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import type { AgentLensEvent, FailureClass, RunStatus } from "@waygent/contracts";
import { appendEvent, readEvents, readLatestRunId, runPaths, sha256 } from "@waygent/lens-store";
import {
  projectApplyReadinessFromState,
  projectExecutionExplanationFromState,
  projectFailureSummary,
  projectOperationalMaturityFromState,
  projectRunReadModel
} from "@waygent/lens-projectors";
import { readRunStateV2Result, writeRunStateV2, type RunStateV2ReadResult, type WaygentRunStateV2 } from "./runState";
export { buildRunEvent, nextRunEvent } from "./runEvents";
import { nextRunEvent } from "./runEvents";
import { applyVerifiedCheckpoint } from "./applyEngine";
import type { PostApplyVerificationSummary } from "./applyEngine";
import { resolveCheckpointPatch, resolveRunArtifactPath, validateCheckpointManifest } from "./checkpointArtifacts";
import { hasApplyReadyCheckpoint } from "./completionAudit";
import { selectResumeAction } from "./recoveryExecutor";

export interface RunCommandOptions {
  root: string;
  run?: string;
  last?: boolean;
}

export interface RunStatusView {
  run_id: string;
  status: RunStatus;
  total_events: number;
  last_event_type: string | null;
  trust_status: string;
}

export function resolveRunId(options: RunCommandOptions): string {
  if (options.run) return options.run;
  if (options.last) {
    const latest = readLatestRunId(options.root);
    if (latest) return latest;
  }
  throw new Error("run id required; pass --run <id> or --last");
}

export function statusRun(options: RunCommandOptions): RunStatusView {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  const stateResult = readRunStateV2Result(options.root, runId);
  const model = projectRunReadModel({
    run_id: runId,
    events,
    ...(stateResult.status === "ok" ? { state: stateResult.state } : { state_error: readModelStateBlocker(stateResult) })
  });
  return {
    run_id: runId,
    status: model.status,
    total_events: model.total_events,
    last_event_type: model.last_event_type,
    trust_status: model.trust_status
  };
}

export function eventsRun(options: RunCommandOptions): { run_id: string; total_events: number; events: AgentLensEvent[] } {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  return { run_id: runId, total_events: events.length, events };
}

export function inspectRun(options: RunCommandOptions): RunStatusView & {
  failures: ReturnType<typeof projectFailureSummary>;
  state?: WaygentRunStateV2;
  execution_explanation?: ReturnType<typeof projectExecutionExplanationFromState>;
  operational_maturity?: ReturnType<typeof projectOperationalMaturityFromState>;
  dogfood_evidence?: ReturnType<typeof projectOperationalMaturityFromState>["dogfood_evidence"];
  runtime_cost?: ReturnType<typeof projectOperationalMaturityFromState>["runtime_cost"];
  provider_readiness?: ReturnType<typeof projectOperationalMaturityFromState>["provider_readiness"];
  state_error?: Exclude<RunStateV2ReadResult, { status: "ok" }>;
} {
  const status = statusRun(options);
  const stateResult = readRunStateV2Result(options.root, status.run_id);
  const events = readEvents(runPaths(options.root, status.run_id).events);
  const model = projectRunReadModel({
    run_id: status.run_id,
    events,
    ...(stateResult.status === "ok" ? { state: stateResult.state } : { state_error: readModelStateBlocker(stateResult) })
  });
  const failures = model.failures;
  if (stateResult.status === "ok") {
    return {
      run_id: model.run_id,
      status: model.status,
      total_events: model.total_events,
      last_event_type: model.last_event_type,
      trust_status: model.trust_status,
      failures,
      state: stateResult.state,
      execution_explanation: model.execution_explanation!,
      operational_maturity: model.operational_maturity!,
      dogfood_evidence: model.operational_maturity!.dogfood_evidence,
      runtime_cost: model.operational_maturity!.runtime_cost,
      provider_readiness: model.operational_maturity!.provider_readiness
    };
  }
  return {
    run_id: model.run_id,
    status: model.status,
    total_events: model.total_events,
    last_event_type: model.last_event_type,
    trust_status: model.trust_status,
    failures,
    state_error: stateResult
  };
}

export function explainRun(options: RunCommandOptions): { run_id: string; blocked_by: FailureClass | "unknown" | null; summary: string } {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  const failure = projectFailureSummary(events)[0] ?? null;
  const stateResult = readRunStateV2Result(options.root, runId);
  if (stateResult.status === "ok") {
    const explanation = projectExecutionExplanationFromState(stateResult.state);
    const maturity = projectOperationalMaturityFromState({ state: stateResult.state, events });
    const stateFailure = blockedTaskFailure(stateResult.state);
    const activeFailure = stateFailure ?? failure;
    const dryRunBlocker = activeFailure ? checkpointDryRunBlocker(events, activeFailure.task_id) : null;
    const barrier = explanation.barriers[0];
    const hotspot = explanation.cost_hotspots[0];
    const dogfoodGap = maturity.dogfood_evidence.status !== "complete"
      ? `dogfood evidence ${maturity.dogfood_evidence.status}: ${maturity.dogfood_evidence.missing_reasons[0] ?? "evidence incomplete"}`
      : null;
    const summaryParts = [
      activeFailure ? failureSummary(activeFailure, dryRunBlocker) : "no active failure barrier",
      barrier ? `scheduling barrier: ${barrier.task_id} ${barrier.reason}` : null,
      hotspot ? `cost hotspot: ${hotspot.phase} ${hotspot.duration_ms}ms` : null,
      !activeFailure && !barrier && !hotspot ? dogfoodGap : null
    ].filter(Boolean);
    return {
      run_id: runId,
      blocked_by: activeFailure?.failure_class ?? null,
      summary: summaryParts.join("; ")
    };
  }
  return {
    run_id: runId,
    blocked_by: failure?.failure_class ?? null,
    summary: failure ? `${failure.task_id} blocked by ${failure.failure_class}` : "no active failure barrier"
  };
}

type StateBlocker = "missing_run_state_v2" | "unsupported_run_state" | "invalid_run_state_v2";

function stateBlocker(result: Exclude<RunStateV2ReadResult, { status: "ok" }>): StateBlocker {
  return result.reason;
}

function readModelStateBlocker(result: Exclude<RunStateV2ReadResult, { status: "ok" }>) {
  if (result.status === "unsupported") return { status: result.status, reason: result.reason, schema: result.schema };
  if (result.status === "invalid") return { status: result.status, reason: result.reason, error: result.error };
  return { status: result.status, reason: result.reason };
}

export function resumeRun(options: RunCommandOptions & { dry_run?: boolean }): {
  run_id: string;
  allowed_actions: string[];
  dry_run: boolean;
  blocked_by?: StateBlocker;
} {
  const explanation = explainRun(options);
  const stateResult = readRunStateV2Result(options.root, explanation.run_id);
  if (stateResult.status !== "ok") {
    return {
      run_id: explanation.run_id,
      allowed_actions: ["inspect_run", "human_decision"],
      dry_run: options.dry_run ?? false,
      blocked_by: stateBlocker(stateResult)
    };
  }
  const v2State = stateResult.state;
  if (v2State.status === "completed") {
    const readiness = projectApplyReadinessFromState(v2State);
    return {
      run_id: explanation.run_id,
      allowed_actions: readiness.status === "ready" && hasApplyReadyCheckpoint(v2State)
        ? ["inspect_run", "apply_verified_checkpoint"]
        : ["inspect_run", "retry_checkpoint_generation", "human_decision"],
      dry_run: options.dry_run ?? false
    };
  }
  const blockedTask = Object.values(v2State.tasks).find((task) =>
    task.status === "blocked" || task.status === "failed" || (v2State.status === "blocked" && Boolean(task.latest_failure_class))
  );
  if (blockedTask?.latest_failure_class) {
    if (blockedTask.latest_failure_class === "needs_rebase") {
      return {
        run_id: explanation.run_id,
        allowed_actions: ["inspect_run", "retry_checkpoint_generation", "human_decision"],
        dry_run: options.dry_run ?? false
      };
    }
    if (blockedTask.latest_failure_class === "dependency_missing" || blockedTask.latest_failure_class === "environment_blocker") {
      return {
        run_id: explanation.run_id,
        allowed_actions: ["rerun_verification"],
        dry_run: options.dry_run ?? false
      };
    }
    const retryCount = Number(v2State.recovery.at(-1)?.retry_count ?? 0);
    const maxRetries = Number(v2State.recovery.at(-1)?.max_retries ?? 1);
    const selection = selectResumeAction({
      failure_class: blockedTask.latest_failure_class,
      retry_count: Number.isFinite(retryCount) ? retryCount : 0,
      max_retries: Number.isFinite(maxRetries) ? maxRetries : 1,
      checkpoint_ref: blockedTask.checkpoint_refs[0] ?? null
    });
    return {
      run_id: explanation.run_id,
      allowed_actions: [selection.action],
      dry_run: options.dry_run ?? false
    };
  }
  return {
    run_id: explanation.run_id,
    allowed_actions: explanation.blocked_by === "verification_failed" ? ["retry_with_evidence", "update_plan"] : ["inspect_run"],
    dry_run: options.dry_run ?? false
  };
}

function blockedTaskFailure(state: WaygentRunStateV2): { task_id: string; failure_class: FailureClass | "unknown" } | null {
  const task = Object.values(state.tasks).find((candidate) =>
    (candidate.status === "blocked" || candidate.status === "failed" || state.status === "blocked") &&
    typeof candidate.latest_failure_class === "string" &&
    candidate.latest_failure_class.length > 0
  );
  if (!task?.latest_failure_class) return null;
  return { task_id: task.id, failure_class: task.latest_failure_class as FailureClass | "unknown" };
}

function failureSummary(
  activeFailure: { task_id: string; failure_class: FailureClass | "unknown" },
  dryRunBlocker: { failed_files: string[]; evidence_ref: string | null } | null
): string {
  if (activeFailure.failure_class !== "needs_rebase" || !dryRunBlocker) {
    return `${activeFailure.task_id} blocked by ${activeFailure.failure_class}`;
  }
  const files = dryRunBlocker.failed_files.length > 0 ? `; files: ${dryRunBlocker.failed_files.join(", ")}` : "";
  const evidence = dryRunBlocker.evidence_ref ? `; evidence: ${dryRunBlocker.evidence_ref}` : "";
  return `${activeFailure.task_id} blocked by needs_rebase: checkpoint patch dry-run failed against current source${files}${evidence}`;
}

function checkpointDryRunBlocker(
  events: AgentLensEvent[],
  taskId: string
): { failed_files: string[]; evidence_ref: string | null } | null {
  const event = [...events].reverse().find((candidate) =>
    candidate.event_type === "runway.apply_dry_run_result" &&
    candidate.outcome === "blocked" &&
    String(candidate.payload.task_id ?? "") === taskId
  );
  const dryRun = event?.payload.dry_run;
  if (!dryRun || typeof dryRun !== "object") return null;
  const payload = dryRun as Record<string, unknown>;
  const failedFiles = Array.isArray(payload.failed_files)
    ? payload.failed_files.filter((item): item is string => typeof item === "string" && item.length > 0)
    : [];
  const evidenceRef = typeof payload.evidence_ref === "string" && payload.evidence_ref.length > 0
    ? payload.evidence_ref
    : null;
  return { failed_files: failedFiles, evidence_ref: evidenceRef };
}

export async function applyRun(options: RunCommandOptions & { workspace: string }): Promise<{
  command: "apply";
  run_id: string;
  status: "blocked" | "applied" | "failed";
  reason?: string;
  post_apply_verification?: PostApplyVerificationSummary;
}> {
  const runId = resolveRunId(options);
  const paths = runPaths(options.root, runId);
  if (isDirtySourceCheckout(options.workspace)) {
    const stateResult = readRunStateV2Result(options.root, runId);
    appendEvent(paths.events, nextRunEvent(paths.events, {
      run_id: runId,
      event_type: "runway.apply_blocked",
      phase: "apply",
      outcome: "blocked",
      summary: "Apply blocked by dirty source checkout.",
      payload: { reason: "dirty_source_checkout" },
      trust_impact: "requires_review"
    }));
    if (stateResult.status === "ok") {
      writeRunStateV2(options.root, { ...stateResult.state, apply: { status: "blocked", reason: "dirty_source_checkout" } });
    }
    return { command: "apply", run_id: runId, status: "blocked", reason: "dirty_source_checkout" };
  }

  const stateResult = readRunStateV2Result(options.root, runId);
  if (stateResult.status !== "ok") {
    const reason = stateBlocker(stateResult);
    appendEvent(paths.events, nextRunEvent(paths.events, {
      run_id: runId,
      event_type: "runway.apply_blocked",
      phase: "apply",
      outcome: "blocked",
      summary: "Apply blocked because Waygent v2 run state is unavailable.",
      payload: { reason },
      trust_impact: "requires_review"
    }));
    return { command: "apply", run_id: runId, status: "blocked", reason };
  }
  const v2State = stateResult.state;

  const readiness = projectApplyReadinessFromState(v2State);
  if (readiness.status !== "ready") {
    const reason = readiness.reason ?? (readiness.status === "applied" ? "already_applied" : "missing_apply_ready_evidence");
    appendEvent(paths.events, nextRunEvent(paths.events, {
      run_id: runId,
      event_type: "runway.apply_blocked",
      phase: "apply",
      outcome: "blocked",
      summary: "Apply blocked because readiness evidence is incomplete.",
      payload: { reason, apply_readiness: readiness },
      trust_impact: "requires_review"
    }));
    writeRunStateV2(options.root, { ...v2State, apply: { status: "blocked", reason } });
    return { command: "apply", run_id: runId, status: "blocked", reason };
  }
  const checkpointRefs = readiness.checkpoint_refs.length > 0 ? readiness.checkpoint_refs : combinedApplyCheckpointRefs(v2State) ?? (v2State.apply.checkpoint_ref
    ? [v2State.apply.checkpoint_ref]
    : Object.values(v2State.tasks)
      .filter((task) => task.status === "verified")
      .flatMap((task) => task.checkpoint_refs));
  if (checkpointRefs.length === 0) {
    appendEvent(paths.events, nextRunEvent(paths.events, {
      run_id: runId,
      event_type: "runway.apply_blocked",
      phase: "apply",
      outcome: "blocked",
      summary: "Apply blocked because no verified checkpoint is available.",
      payload: { reason: "missing_verified_checkpoint" },
      trust_impact: "requires_review"
    }));
    writeRunStateV2(options.root, { ...v2State, apply: { status: "blocked", reason: "missing_verified_checkpoint" } });
    return { command: "apply", run_id: runId, status: "blocked", reason: "missing_verified_checkpoint" };
  }
  const failedValidation = checkpointRefs
    .map((checkpointRef) => ({ checkpointRef, validation: validateCheckpointManifest(v2State.run_root, checkpointRef) }))
    .find((item) => !item.validation.ok);
  if (failedValidation) {
    const reason = failedValidation.validation.reason ?? "missing_verified_checkpoint";
    appendEvent(paths.events, nextRunEvent(paths.events, {
      run_id: runId,
      event_type: "runway.apply_blocked",
      phase: "apply",
      outcome: "blocked",
      summary: "Apply blocked because no verified checkpoint is available.",
      payload: { checkpoint_ref: failedValidation.checkpointRef, reason },
      trust_impact: "requires_review"
    }));
    writeRunStateV2(options.root, { ...v2State, apply: { status: "blocked", reason } });
    return { command: "apply", run_id: runId, status: "blocked", reason };
  }
  const resolved = checkpointRefs.map((checkpointRef) => ({
    checkpointRef,
    resolved: resolveCheckpointPatch(v2State.run_root, checkpointRef)
  }));
  if (resolved.some((item) => !item.resolved)) {
    writeRunStateV2(options.root, { ...v2State, apply: { status: "blocked", reason: "missing_verified_checkpoint" } });
    return { command: "apply", run_id: runId, status: "blocked", reason: "missing_verified_checkpoint" };
  }
  const combinedPatch = readCombinedApplyPatch(v2State);
  if (combinedPatch.status === "blocked") {
    appendEvent(paths.events, nextRunEvent(paths.events, {
      run_id: runId,
      event_type: "runway.apply_blocked",
      phase: "apply",
      outcome: "blocked",
      summary: "Apply blocked because the materialized checkpoint patch is unavailable.",
      payload: { checkpoint_refs: checkpointRefs, reason: combinedPatch.reason },
      trust_impact: "requires_review"
    }));
    writeRunStateV2(options.root, { ...v2State, apply: { status: "blocked", reason: combinedPatch.reason } });
    return { command: "apply", run_id: runId, status: "blocked", reason: combinedPatch.reason };
  }
  const finalTaskIds = finalContributingTaskIds(resolved, changedFilesFromPatch(combinedPatch.patch));
  const postApplyCommands = v2State.verification
    .filter((record) => {
      const taskId = record.task_id;
      return typeof taskId !== "string" || finalTaskIds.size === 0 || finalTaskIds.has(taskId);
    })
    .map((record) => record.command)
    .filter((command): command is string => typeof command === "string" && command.trim().length > 0);
  const applied = await applyVerifiedCheckpoint({
    source: options.workspace,
    patch: combinedPatch.patch,
    post_apply_commands: postApplyCommands.length > 0 ? postApplyCommands : ["git diff --check"]
  });
  appendEvent(paths.events, nextRunEvent(paths.events, {
    run_id: runId,
    event_type: applied.status === "applied" ? "runway.apply_completed" : applied.status === "blocked" ? "runway.apply_blocked" : "runway.apply_failed",
    phase: "apply",
    outcome: applied.status === "applied" ? "success" : applied.status === "blocked" ? "blocked" : "failed",
    summary: applied.status === "applied" ? "Verified checkpoint applied." : "Verified checkpoint apply did not complete.",
    payload: {
      checkpoint_refs: checkpointRefs,
      reason: applied.reason ?? null,
      ...(applied.post_apply_verification ? { post_apply_verification: applied.post_apply_verification } : {})
    },
    trust_impact: applied.status === "applied" ? "supports_success" : "requires_review"
  }));
  writeRunStateV2(options.root, {
    ...v2State,
    status: applied.status === "applied" ? "applied" : v2State.status,
    current_phase: "apply",
    apply: { status: applied.status, checkpoint_ref: checkpointRefs[0]!, ...(applied.reason ? { reason: applied.reason } : {}) }
  });
  return {
    command: "apply",
    run_id: runId,
    status: applied.status,
    ...(applied.reason ? { reason: applied.reason } : {}),
    ...(applied.post_apply_verification ? { post_apply_verification: applied.post_apply_verification } : {})
  };
}

function finalContributingTaskIds(
  resolved: Array<{ checkpointRef: string; resolved: ReturnType<typeof resolveCheckpointPatch> }>,
  finalPatchFiles: Set<string>
): Set<string> {
  const seenFiles = new Set<string>();
  const taskIds = new Set<string>();
  for (let index = resolved.length - 1; index >= 0; index -= 1) {
    const manifest = resolved[index]?.resolved?.manifest;
    if (!manifest) continue;
    const finalFiles = manifest.changed_files.filter((file) => finalPatchFiles.has(file));
    const contributes = finalFiles.some((file) => !seenFiles.has(file));
    for (const file of finalFiles) seenFiles.add(file);
    if (contributes) taskIds.add(manifest.task_id);
  }
  return taskIds;
}

function combinedApplyCheckpointRefs(state: WaygentRunStateV2): string[] | null {
  const refs = (state.completion_audit as {
    combined_apply_evidence?: { checkpoint_refs?: unknown };
  } | null)?.combined_apply_evidence?.checkpoint_refs;
  if (!Array.isArray(refs)) return null;
  const checkpointRefs = refs.filter((ref): ref is string => typeof ref === "string" && ref.length > 0);
  return checkpointRefs.length > 0 ? checkpointRefs : null;
}

function changedFilesFromPatch(patch: string): Set<string> {
  const files = new Set<string>();
  for (const line of patch.split("\n")) {
    if (line.startsWith("+++ b/")) files.add(line.slice("+++ b/".length));
    if (line.startsWith("--- a/")) files.add(line.slice("--- a/".length));
  }
  files.delete("/dev/null");
  return files;
}

function readCombinedApplyPatch(state: WaygentRunStateV2):
  | { status: "ready"; patch: string; reason?: never }
  | { status: "blocked"; reason: "checkpoint_patch_missing" | "checkpoint_digest_mismatch"; patch?: never } {
  const combined = (state.completion_audit as {
    combined_apply_evidence?: { status?: string; patch_ref?: string; patch_sha256?: string; patch_byte_length?: number };
  } | null)?.combined_apply_evidence;
  if (!combined) return { status: "blocked", reason: "checkpoint_patch_missing" };
  if (combined.status !== "passed" || !combined.patch_ref) return { status: "blocked", reason: "checkpoint_patch_missing" };
  try {
    const patch = readFileSync(resolveRunArtifactPath(state.run_root, combined.patch_ref));
    if (combined.patch_sha256 && sha256(patch) !== combined.patch_sha256) {
      return { status: "blocked", reason: "checkpoint_digest_mismatch" };
    }
    if (typeof combined.patch_byte_length === "number" && patch.byteLength !== combined.patch_byte_length) {
      return { status: "blocked", reason: "checkpoint_digest_mismatch" };
    }
    return { status: "ready", patch: patch.toString("utf8") };
  } catch {
    return { status: "blocked", reason: "checkpoint_patch_missing" };
  }
}

function isDirtySourceCheckout(workspace: string): boolean {
  const gitStatus = spawnSync("git", ["status", "--porcelain"], {
    cwd: workspace,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (gitStatus.status === 0) {
    return gitStatus.stdout.trim().length > 0;
  }
  return readdirSync(workspace).some((entry) => !entry.startsWith(".git"));
}
