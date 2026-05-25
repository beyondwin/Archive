import { existsSync, readdirSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import type { AgentLensEvent, FailureClass, OperatorDecisionProjection, RunStatus } from "@waygent/contracts";
import { appendEvent, readEvents, readLatestRunId, runPaths, sha256, writeArtifact } from "@waygent/lens-store";
import {
  projectApplyReadinessFromState,
  projectExecutionExplanationFromState,
  projectFailureBarrierFromState,
  projectFailureSummary,
  projectOperationalMaturityFromState,
  projectOperatorDecisionFromState,
  projectRunReadModel
} from "@waygent/lens-projectors";
import { readRunStateV2Result, writeRunStateV2, type RunStateV2ReadResult, type WaygentRunStateV2 } from "./runState";
export { buildRunEvent, nextRunEvent } from "./runEvents";
import { nextRunEvent } from "./runEvents";
import { applyVerifiedCheckpoint } from "./applyEngine";
import type { PostApplyVerificationSummary } from "./applyEngine";
import { resolveCheckpointPatch, resolveRunArtifactPath, validateCheckpointManifest } from "./checkpointArtifacts";
import { buildCompletionAudit, hasApplyReadyCheckpoint } from "./completionAudit";
import { selectResumeAction } from "./recoveryExecutor";
import { validateMethodEvidenceForApply } from "./evidencePolicy";
import { deleteResolvedOrphan, scanOrphanRuns } from "./orphanRuns";
import { runVerificationCommands } from "./verification";
import { watchRun, type WatchRunOptions } from "./watchRun";
import { reconcileRunState } from "./stateReconciliation";
import { taskIsReadOnlyOnly, taskRequiresCheckpoint } from "./taskCheckpointPolicy";
import { evaluateTerminalCompletionInvariant } from "./terminalInvariant";

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

export interface VerifyRunResult {
  command: "verify";
  run_id: string;
  status: "passed" | "failed" | "blocked";
  verification_refs: string[];
  total_results: number;
  task_id?: string;
  reason?: string;
  failure_class?: FailureClass | string | null;
  failure_summary?: string | null;
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
  const paths = runPaths(options.root, runId);
  // Guard against a stale `latest` pointer whose run directory has been
  // removed out-of-band: without this check, status silently reports
  // status:"running" total_events:0 last_event_type:null which is
  // indistinguishable from a freshly-spawned run that has not emitted yet.
  if (!existsSync(paths.root) && !existsSync(paths.events)) {
    return {
      run_id: runId,
      status: "failed",
      total_events: 0,
      last_event_type: "evidence_cleared",
      trust_status: "evidence_missing"
    };
  }
  const events = readEvents(paths.events);
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

function blockedVerifyResult(runId: string, reason: string, taskId?: string): VerifyRunResult {
  const result: VerifyRunResult = {
    command: "verify",
    run_id: runId,
    status: "blocked",
    reason,
    verification_refs: [],
    total_results: 0
  };
  if (taskId) result.task_id = taskId;
  return result;
}

function selectVerificationTask(state: WaygentRunStateV2, explicitTaskId?: string): {
  task: WaygentRunStateV2["tasks"][string] | null;
  reason: string;
  task_id?: string;
} {
  if (explicitTaskId) {
    const task = state.tasks[explicitTaskId] ?? null;
    return task ? { task, reason: "selected" } : { task: null, reason: "unknown_task", task_id: explicitTaskId };
  }
  const tasks = Object.values(state.tasks);
  const verificationBlocked = tasks.filter((task) =>
    (task.status === "blocked" || task.status === "failed")
    && isVerificationFailureClass(task.latest_failure_class)
  );
  if (verificationBlocked.length === 1) return { task: verificationBlocked[0]!, reason: "selected" };
  const blocked = tasks.filter((task) => task.status === "blocked" || task.status === "failed");
  if (blocked.length === 1) return { task: blocked[0]!, reason: "selected" };
  if (tasks.length === 1) return { task: tasks[0]!, reason: "selected" };
  return { task: null, reason: tasks.length === 0 ? "no_tasks" : "ambiguous_task_selection" };
}

function isVerificationFailureClass(value: FailureClass | string | null): boolean {
  return value === "verification_failed"
    || value === "dependency_missing"
    || value === "environment_blocker"
    || value === "command_not_found"
    || value === "permission_denied"
    || value === "timeout";
}

function readTaskPacketVerificationCommands(path: string): string[] {
  const parsed = JSON.parse(readFileSync(path, "utf8")) as {
    verification_commands?: unknown;
    acceptance_commands?: unknown;
  };
  const verification = stringArray(parsed.verification_commands);
  return verification.length > 0 ? verification : stringArray(parsed.acceptance_commands);
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function nextVerificationFailureClass(task: WaygentRunStateV2["tasks"][string], status: "passed" | "failed"): FailureClass | string | null {
  if (status === "failed") return task.latest_failure_class;
  const needsCheckpoint = taskRequiresCheckpoint(task) && task.checkpoint_refs.length === 0;
  return needsCheckpoint ? "missing_checkpoint" : null;
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

export async function verifyRun(options: RunCommandOptions & { task?: string }): Promise<VerifyRunResult> {
  const runId = resolveRunId(options);
  const stateResult = readRunStateV2Result(options.root, runId);
  if (stateResult.status !== "ok") {
    return blockedVerifyResult(runId, stateBlocker(stateResult));
  }
  const state = stateResult.state;
  const selection = selectVerificationTask(state, options.task);
  if (!selection.task) return blockedVerifyResult(runId, selection.reason, selection.task_id);
  const task = selection.task;
  if (!task.task_packet_path || !existsSync(task.task_packet_path)) {
    return blockedVerifyResult(runId, "missing_task_packet", task.id);
  }
  const commands = readTaskPacketVerificationCommands(task.task_packet_path);
  if (commands.length === 0) return blockedVerifyResult(runId, "missing_verification_commands", task.id);
  const worktree = state.worktrees?.find((item) => item.task_id === task.id && item.cleanup_status === "active");
  if (!worktree || !existsSync(worktree.path)) return blockedVerifyResult(runId, "missing_task_worktree", task.id);

  const verifiedAt = new Date().toISOString();
  const verification = await runVerificationCommands({
    run_id: runId,
    task_id: task.id,
    cwd: worktree.path,
    commands
  });
  const paths = runPaths(options.root, runId);
  const verificationRecords = verification.results.map((kernel, index) => {
    const artifact = writeArtifact(
      paths.root,
      `kernel/rerun_${task.id}_${index + 1}_${Date.now()}.json`,
      `${JSON.stringify(kernel, null, 2)}\n`
    );
    const passed = kernel.exit_code === 0 && !kernel.timed_out;
    return {
      verification_id: kernel.request_id,
      task_id: task.id,
      command: commands[index] ?? "",
      status: passed ? "passed" : "failed",
      kernel_result_ref: artifact.path,
      kernel_result_sha256: artifact.sha256,
      rerun: true,
      verified_at: verifiedAt,
      failure_class: passed ? null : verification.failure_class,
      failure_summary: passed ? null : verification.failure_summary
    };
  });
  const verificationRefs = verificationRecords.map((record) => String(record.kernel_result_ref));
  const readOnlyWorktreeFailure = verification.status === "passed" ? readOnlyWorktreeFailureClass(task, worktree.path) : null;
  const nextFailureClass = readOnlyWorktreeFailure ?? nextVerificationFailureClass(task, verification.status);
  const effectiveStatus = verification.status === "passed" && nextFailureClass !== null ? "failed" : verification.status;
  const failureSummary = readOnlyWorktreeFailure
    ? "read-only verification worktree has uncheckpointed changes"
    : verification.failure_summary;
  const nextTaskStatus = effectiveStatus === "passed" && nextFailureClass === null ? "verified" : "blocked";
  const nextTasks: WaygentRunStateV2["tasks"] = {
    ...state.tasks,
    [task.id]: {
      ...task,
      status: nextTaskStatus,
      latest_failure_class: effectiveStatus === "passed" ? nextFailureClass : nextFailureClass ?? verification.failure_class,
      timing: { ...task.timing, verification_rerun_at: verifiedAt }
    }
  };
  const allTasksVerified = Object.values(nextTasks).every((item) => item.status === "verified");
  const nextStateBase: WaygentRunStateV2 = {
    ...state,
    tasks: nextTasks,
    verification: [...state.verification, ...verificationRecords],
    status: allTasksVerified ? "running" : "blocked",
    lifecycle_outcome: allTasksVerified ? null : "blocked",
    current_phase: allTasksVerified ? "complete" : "recover",
    timestamps: {
      ...state.timestamps,
      updated_at: verifiedAt,
      completed_at: allTasksVerified ? state.timestamps.completed_at : state.timestamps.completed_at
    }
  };
  let nextState: WaygentRunStateV2 = {
    ...nextStateBase,
    completion_audit: refreshedCompletionAudit(nextStateBase, commands)
  };
  writeRunStateV2(options.root, nextState);
  if (allTasksVerified) {
    const reconciliation = reconcileRunState(options.root, runId);
    const reconciled = readRunStateV2Result(options.root, runId);
    if (reconciled.status === "ok") {
      const refreshed = refreshedCompletionAudit(reconciled.state, commands);
      const completionAudit = finalizeCompletionAudit(reconciled.state, refreshed, reconciliation);
      const terminalPassed = completionAuditStatus(completionAudit) === "passed";
      nextState = {
        ...reconciled.state,
        completion_audit: completionAudit,
        status: terminalPassed ? "completed" : "blocked",
        lifecycle_outcome: terminalPassed ? "finished" : "blocked",
        current_phase: terminalPassed ? "complete" : "recover",
        timestamps: {
          ...reconciled.state.timestamps,
          updated_at: verifiedAt,
          completed_at: terminalPassed ? reconciled.state.timestamps.completed_at ?? verifiedAt : reconciled.state.timestamps.completed_at
        }
      };
      writeRunStateV2(options.root, nextState);
    }
  }
  appendEvent(paths.events, nextRunEvent(paths.events, {
    run_id: runId,
    event_type: "runway.verification_result",
    phase: "verify",
    outcome: effectiveStatus === "passed" ? "success" : "failed",
    summary: effectiveStatus === "passed" ? "Verification rerun passed." : "Verification rerun failed.",
    payload: {
      task_id: task.id,
      rerun: true,
      commands: commands.length,
      verification_refs: verificationRefs,
      failure_class: nextFailureClass ?? verification.failure_class,
      failure_summary: failureSummary
    },
    trust_impact: effectiveStatus === "passed" ? "supports_success" : "supports_failure"
  }));
  return {
    command: "verify",
    run_id: runId,
    task_id: task.id,
    status: effectiveStatus,
    verification_refs: verificationRefs,
    total_results: verification.results.length,
    failure_class: nextFailureClass ?? verification.failure_class,
    failure_summary: failureSummary
  };
}

function readOnlyWorktreeFailureClass(task: WaygentRunStateV2["tasks"][string], cwd: string): FailureClass | null {
  if (!taskIsReadOnlyOnly(task)) return null;
  const status = spawnSync("git", ["status", "--porcelain", "--untracked-files=all"], {
    cwd,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (status.status !== 0 || status.stdout.trim().length > 0) return "state_drift";
  return null;
}

function refreshedCompletionAudit(state: WaygentRunStateV2, fallbackRequiredChecks: string[]): WaygentRunStateV2["completion_audit"] {
  const previous = state.completion_audit as {
    required_checks?: unknown;
    review_evidence?: unknown;
    combined_apply_evidence?: unknown;
    prompt_to_artifact_checklist?: unknown;
  } | null;
  if (!previous) return state.completion_audit;
  const auditInput: Parameters<typeof buildCompletionAudit>[0] = {
    state,
    required_checks: stringArray(previous.required_checks).length > 0
      ? stringArray(previous.required_checks)
      : fallbackRequiredChecks,
    verification_evidence: state.verification as Array<Record<string, unknown>>,
    review_evidence: recordArray(previous.review_evidence),
    prompt_to_artifact_checklist: stringArray(previous.prompt_to_artifact_checklist)
  };
  if (previous.combined_apply_evidence) {
    auditInput.combined_apply_evidence = previous.combined_apply_evidence as NonNullable<Parameters<typeof buildCompletionAudit>[0]["combined_apply_evidence"]>;
  }
  return buildCompletionAudit(auditInput);
}

function finalizeCompletionAudit(
  state: WaygentRunStateV2,
  audit: WaygentRunStateV2["completion_audit"],
  reconciliation: { passed: boolean; records: unknown[]; unrepaired_blockers: unknown[] }
): WaygentRunStateV2["completion_audit"] {
  if (!audit) return audit;
  const auditResidualRisk = Array.isArray((audit as { residual_risk?: unknown }).residual_risk)
    ? (audit as { residual_risk: unknown[] }).residual_risk.map(String)
    : ["completion_audit:missing_residual_risk"];
  const reconciliationResidualRisk = reconciliation.passed ? [] : ["state_reconciliation:blocking"];
  const withReconciliation = {
    ...audit,
    state_reconciliation: reconciliation,
    status: audit.status === "passed" && reconciliation.passed ? "passed" : "failed",
    residual_risk: [...new Set([...auditResidualRisk, ...reconciliationResidualRisk])]
  };
  const terminalState = { ...state, completion_audit: withReconciliation };
  const terminalInvariant = evaluateTerminalCompletionInvariant(terminalState);
  const terminalResidualRisk = terminalInvariant.blockers.map((blocker) => `terminal_invariant:${blocker.code}`);
  const residualRisk = Array.isArray(withReconciliation.residual_risk)
    ? withReconciliation.residual_risk.map(String)
    : [];
  return {
    ...withReconciliation,
    terminal_invariant: terminalInvariant,
    status: terminalInvariant.passed ? "passed" : "failed",
    residual_risk: terminalInvariant.passed ? [] : [...new Set([...residualRisk, ...terminalResidualRisk])]
  };
}

function completionAuditStatus(audit: WaygentRunStateV2["completion_audit"]): string | null {
  if (!audit || typeof audit !== "object" || Array.isArray(audit)) return null;
  const status = (audit as { status?: unknown }).status;
  return typeof status === "string" ? status : null;
}

function recordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null && !Array.isArray(item))
    : [];
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
  let v2State = stateResult.state;
  // The live isDirtySourceCheckout above passed. If the cached apply state still
  // says blocked-by-dirty-source from a prior attempt, that record is stale and
  // would otherwise leak through projectApplyReadinessFromState as the readiness
  // reason. Reset to not_ready so downstream readiness reflects real evidence.
  if (v2State.apply.status === "blocked" && v2State.apply.reason === "dirty_source_checkout") {
    const { reason: _stale, ...applyRest } = v2State.apply;
    v2State = { ...v2State, apply: { ...applyRest, status: "not_ready" } };
    writeRunStateV2(options.root, v2State);
  }
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
