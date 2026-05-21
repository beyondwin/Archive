import { readdirSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import type { AgentLensEvent, FailureClass, RunStatus } from "@waygent/contracts";
import { appendEvent, readEvents, readLatestRunId, rebuildRunSummary, runPaths, sha256 } from "@waygent/lens-store";
import { projectApplyReadinessFromState, projectFailureSummary, projectTrustReport } from "@waygent/lens-projectors";
import { hasRunState, readRunState, writeRunState, type WaygentRunState } from "./runState";
export { buildRunEvent, nextRunEvent } from "./runEvents";
import { nextRunEvent } from "./runEvents";
import { applyVerifiedCheckpoint } from "./applyEngine";
import { resolveCheckpointPatch, resolveRunArtifactPath, validateCheckpointManifest } from "./checkpointArtifacts";
import { hasApplyReadyCheckpoint } from "./completionAudit";
import { selectResumeAction } from "./recoveryExecutor";
import { readRunStateV2, writeRunStateV2 } from "./runState";

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
  const summary = rebuildRunSummary(events);
  const trust = projectTrustReport(events);
  const blocked = events.some((event) => event.outcome === "blocked");
  const failed = events.some((event) => event.outcome === "failed");
  const status: RunStatus = blocked ? "blocked" : failed ? "failed" : trust.trust_status === "trusted" ? "completed" : "running";
  return {
    run_id: runId,
    status,
    total_events: summary.total_events,
    last_event_type: summary.last_event_type,
    trust_status: trust.trust_status
  };
}

export function eventsRun(options: RunCommandOptions): { run_id: string; total_events: number; events: AgentLensEvent[] } {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  return { run_id: runId, total_events: events.length, events };
}

export function inspectRun(options: RunCommandOptions): RunStatusView & {
  failures: ReturnType<typeof projectFailureSummary>;
  state?: WaygentRunState;
} {
  const status = statusRun(options);
  return {
    ...status,
    failures: projectFailureSummary(readEvents(runPaths(options.root, status.run_id).events)),
    ...(hasRunState(options.root, status.run_id) ? { state: readRunState(options.root, status.run_id) } : {})
  };
}

export function explainRun(options: RunCommandOptions): { run_id: string; blocked_by: FailureClass | "unknown" | null; summary: string } {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  const failure = projectFailureSummary(events)[0] ?? null;
  return {
    run_id: runId,
    blocked_by: failure?.failure_class ?? null,
    summary: failure ? `${failure.task_id} blocked by ${failure.failure_class}` : "no active failure barrier"
  };
}

export function resumeRun(options: RunCommandOptions & { dry_run?: boolean }): { run_id: string; allowed_actions: string[]; dry_run: boolean } {
  const explanation = explainRun(options);
  if (hasRunState(options.root, explanation.run_id)) {
    const v2State = tryReadRunStateV2(options.root, explanation.run_id);
    if (v2State) {
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
    }
    const state = readRunState(options.root, explanation.run_id);
    if (state.status === "completed") {
      return {
        run_id: explanation.run_id,
        allowed_actions: ["inspect_run", "apply_verified_checkpoint"],
        dry_run: options.dry_run ?? false
      };
    }
  }
  return {
    run_id: explanation.run_id,
    allowed_actions: explanation.blocked_by === "verification_failed" ? ["retry_with_evidence", "update_plan"] : ["inspect_run"],
    dry_run: options.dry_run ?? false
  };
}

function tryReadRunStateV2(root: string, runId: string) {
  try {
    return readRunStateV2(root, runId);
  } catch {
    return null;
  }
}

export async function applyRun(options: RunCommandOptions & { workspace: string }): Promise<{
  command: "apply";
  run_id: string;
  status: "blocked" | "applied" | "failed";
  reason?: string;
}> {
  const runId = resolveRunId(options);
  const paths = runPaths(options.root, runId);
  const v2State = hasRunState(options.root, runId) ? tryReadRunStateV2(options.root, runId) : null;
  if (isDirtySourceCheckout(options.workspace)) {
    appendEvent(paths.events, nextRunEvent(paths.events, {
      run_id: runId,
      event_type: "runway.apply_blocked",
      phase: "apply",
      outcome: "blocked",
      summary: "Apply blocked by dirty source checkout.",
      payload: { reason: "dirty_source_checkout" },
      trust_impact: "requires_review"
    }));
    if (v2State) {
      writeRunStateV2(options.root, { ...v2State, apply: { status: "blocked", reason: "dirty_source_checkout" } });
    } else if (hasRunState(options.root, runId)) {
      const state = readRunState(options.root, runId);
      writeRunState(options.root, { ...state, apply: { status: "blocked", reason: "dirty_source_checkout" } });
    }
    return { command: "apply", run_id: runId, status: "blocked", reason: "dirty_source_checkout" };
  }

  if (v2State) {
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
      payload: { checkpoint_refs: checkpointRefs, reason: applied.reason ?? null },
      trust_impact: applied.status === "applied" ? "supports_success" : "requires_review"
    }));
    writeRunStateV2(options.root, {
      ...v2State,
      status: applied.status === "applied" ? "applied" : v2State.status,
      current_phase: "apply",
      apply: { status: applied.status, checkpoint_ref: checkpointRefs[0]!, ...(applied.reason ? { reason: applied.reason } : {}) }
    });
    return { command: "apply", run_id: runId, status: applied.status, ...(applied.reason ? { reason: applied.reason } : {}) };
  }

  const checkpointRef = hasRunState(options.root, runId)
    ? readRunState(options.root, runId).tasks.find((task) => task.checkpoint_ref)?.checkpoint_ref
    : undefined;
  appendEvent(paths.events, nextRunEvent(paths.events, {
    run_id: runId,
    event_type: "runway.apply_completed",
    phase: "apply",
    outcome: "success",
    summary: "Verified checkpoint applied.",
    payload: { checkpoint_ref: checkpointRef ?? null }
  }));
  if (hasRunState(options.root, runId)) {
    const state = readRunState(options.root, runId);
    writeRunState(options.root, { ...state, status: "completed", apply: { status: "applied" } });
  }
  return { command: "apply", run_id: runId, status: "applied" };
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

function combinedApplyCheckpointRefs(state: ReturnType<typeof readRunStateV2>): string[] | null {
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

function readCombinedApplyPatch(state: ReturnType<typeof readRunStateV2>):
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
