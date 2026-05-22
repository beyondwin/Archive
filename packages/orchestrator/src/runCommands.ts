import { readdirSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import type { AgentLensEvent, FailureClass, OperatorDecisionProjection, RunStatus } from "@waygent/contracts";
import { appendEvent, readEvents, readLatestRunId, runPaths, sha256 } from "@waygent/lens-store";
import {
  projectApplyReadinessFromState,
  projectExecutionExplanationFromState,
  projectFailureSummary,
  projectOperationalMaturityFromState,
  projectOperatorDecisionFromState,
  projectFailureBarrierFromState,
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
import { validateMethodEvidenceForApply } from "./evidencePolicy";
import { deleteResolvedOrphan, scanOrphanRuns } from "./orphanRuns";
import { watchRun, type WatchRunOptions } from "./watchRun";

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
  operator_decision: OperatorDecisionProjection;
  failure_barrier?: ReturnType<typeof projectFailureBarrierFromState>;
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
    const executionExplanation = model.execution_explanation!;
    const operationalMaturity = model.operational_maturity!;
    const operatorDecisionInput = {
      state: stateResult.state,
      events,
      apply_readiness: projectApplyReadinessFromState(stateResult.state),
      execution_explanation: executionExplanation,
      operational_maturity: operationalMaturity
    };
    const operatorDecision = projectOperatorDecisionFromState(operatorDecisionInput);
    return {
      run_id: model.run_id,
      status: model.status,
      total_events: model.total_events,
      last_event_type: model.last_event_type,
      trust_status: model.trust_status,
      failures,
      state: stateResult.state,
      execution_explanation: executionExplanation,
      operational_maturity: operationalMaturity,
      dogfood_evidence: operationalMaturity.dogfood_evidence,
      runtime_cost: operationalMaturity.runtime_cost,
      provider_readiness: operationalMaturity.provider_readiness,
      operator_decision: operatorDecision,
      failure_barrier: projectFailureBarrierFromState(stateResult.state)
    };
  }
  const operatorDecisionInput = {
    state: null,
    events,
    run_id: status.run_id,
    state_error: stateResult
  };
  const operatorDecision = projectOperatorDecisionFromState(operatorDecisionInput);
  return {
    run_id: model.run_id,
    status: model.status,
    total_events: model.total_events,
    last_event_type: model.last_event_type,
    trust_status: model.trust_status,
    failures,
    operator_decision: operatorDecision,
    state_error: stateResult
  };
}

export function explainRun(options: RunCommandOptions): {
  run_id: string;
  blocked_by: FailureClass | "unknown" | null;
  summary: string;
  operator_decision: OperatorDecisionProjection;
  failure_barrier?: ReturnType<typeof projectFailureBarrierFromState>;
} {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  const stateResult = readRunStateV2Result(options.root, runId);
  let operatorDecision: OperatorDecisionProjection;
  if (stateResult.status === "ok") {
    const executionExplanation = projectExecutionExplanationFromState(stateResult.state);
    const operationalMaturity = projectOperationalMaturityFromState({ state: stateResult.state, events });
    const operatorDecisionInput = {
      state: stateResult.state,
      events,
      apply_readiness: projectApplyReadinessFromState(stateResult.state),
      execution_explanation: executionExplanation,
      operational_maturity: operationalMaturity
    };
    operatorDecision = projectOperatorDecisionFromState(operatorDecisionInput);
  } else {
    const operatorDecisionInput = {
      state: null,
      events,
      run_id: runId,
      state_error: stateResult
    };
    operatorDecision = projectOperatorDecisionFromState(operatorDecisionInput);
  }
  return {
    run_id: runId,
    blocked_by: operatorDecision.primary_blocker ? operatorDecision.primary_blocker.code as FailureClass | "unknown" : null,
    summary: operatorDecision.status_summary.summary,
    operator_decision: operatorDecision,
    ...(stateResult.status === "ok" ? { failure_barrier: projectFailureBarrierFromState(stateResult.state) } : {})
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

export async function applyRun(options: RunCommandOptions & { workspace: string; require_method_evidence?: boolean }): Promise<{
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
  const methodEvidence = validateMethodEvidenceForApply({
    state: v2State,
    require_method_evidence: options.require_method_evidence ?? v2State.method_evidence_required ?? false
  });
  if (methodEvidence.status === "blocked") {
    appendEvent(paths.events, nextRunEvent(paths.events, {
      run_id: runId,
      event_type: "lens.evidence_apply_blocked",
      phase: "apply",
      outcome: "blocked",
      summary: "Apply blocked by missing method evidence.",
      payload: { ...methodEvidence },
      trust_impact: "requires_review"
    }));
    writeRunStateV2(options.root, {
      ...v2State,
      tasks: Object.fromEntries(Object.entries(v2State.tasks).map(([taskId, task]) => [
        taskId,
        { ...task, ...(methodEvidence.policies[taskId] ? { evidence_policy: methodEvidence.policies[taskId] } : {}) }
      ])),
      apply: { status: "blocked", reason: methodEvidence.reason ?? "method_evidence_missing" }
    });
    return { command: "apply", run_id: runId, status: "blocked", reason: methodEvidence.reason ?? "method_evidence_missing" };
  }
  if (options.require_method_evidence ?? v2State.method_evidence_required ?? false) {
    appendEvent(paths.events, nextRunEvent(paths.events, {
      run_id: runId,
      event_type: "lens.evidence_apply_gated",
      phase: "apply",
      outcome: "success",
      summary: "Method evidence policy passed before apply.",
      payload: { ...methodEvidence },
      trust_impact: "supports_success"
    }));
  }

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

export function decisionsRun(options: RunCommandOptions): {
  run_id: string;
  decisions: NonNullable<WaygentRunStateV2["decisions_register"]>;
  decision_count: number;
  markdown_ref: string;
} {
  const runId = resolveRunId(options);
  const state = readRunStateV2Result(options.root, runId);
  if (state.status !== "ok") throw new Error(state.reason);
  return {
    run_id: runId,
    decisions: state.state.decisions_register ?? [],
    decision_count: state.state.decisions_register?.length ?? 0,
    markdown_ref: `${state.state.run_root}/DECISIONS.md`
  };
}

export function costRun(options: RunCommandOptions): {
  run_id: string;
  cost_ledger: WaygentRunStateV2["cost_ledger"] | null;
  budget_cap_usd: number | null;
  budget_action: WaygentRunStateV2["budget_action"] | null;
} {
  const runId = resolveRunId(options);
  const state = readRunStateV2Result(options.root, runId);
  if (state.status !== "ok") throw new Error(state.reason);
  return {
    run_id: runId,
    cost_ledger: state.state.cost_ledger ?? null,
    budget_cap_usd: state.state.budget_cap_usd ?? null,
    budget_action: state.state.budget_action ?? null
  };
}

export function watchRunCommand(options: WatchRunOptions): ReturnType<typeof watchRun> {
  return watchRun(options);
}

export function orphansRun(options: RunCommandOptions & { delete?: string; yes?: boolean }): ReturnType<typeof scanOrphanRuns> | ReturnType<typeof deleteResolvedOrphan> {
  const advisory = scanOrphanRuns({ root: options.root });
  if (options.delete) return deleteResolvedOrphan({ root: options.root, id: options.delete, yes: Boolean(options.yes), advisory });
  return advisory;
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
