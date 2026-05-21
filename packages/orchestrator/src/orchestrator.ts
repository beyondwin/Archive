import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { AgentLensEvent, WaygentRunStateV2 } from "@waygent/contracts";
import { planWorktree } from "@waygent/kernel-client";
import { projectFailureSummary, projectTimeline, projectTrustReport } from "@waygent/lens-projectors";
import { appendEvent, readEvents, rebuildRunSummary, runPaths, writeLatestRunId } from "@waygent/lens-store";
import type { ProviderProcessOptions } from "@waygent/provider-adapters";
import { buildDurableProjection } from "@waygent/runway-control";
import { createCombinedCheckpointPatchArtifact } from "./checkpointArtifacts";
import { buildCompletionAudit } from "./completionAudit";
import { resolveExecutionProfile, type ExecutionProfile, type ProfileOverride, type ProviderName } from "./executionProfile";
import { resolvePlanInput } from "./planDiscovery";
import { parseWaygentPlan } from "./planParser";
import { buildRunEvent } from "./runEvents";
import { createRunExecutionContext, type RunExecutionContext } from "./runExecutionContext";
import { classifySourceCheckout } from "./sourceCheckout";
import { reconcileRunState } from "./stateReconciliation";
import { buildTaskGraphFromPlan } from "./taskGraph";
import { executeBoundedSafeWave, resolveWaveConcurrency } from "./safeWaveExecutor";
import { executeWaygentTask, type WaygentTaskExecutionResult } from "./taskExecutor";

export interface RunWaygentOptions {
  root: string;
  run_id?: string;
  profile?: ProfileOverride;
  plan?: string;
  plan_path?: string;
  latest?: boolean;
  topic?: string;
  workspace?: string;
  worktree_root?: string;
  spec?: string;
  provider_processes?: Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>>;
}

export interface WaygentRunResult {
  run_id: string;
  events: AgentLensEvent[];
  trust_report: ReturnType<typeof projectTrustReport>;
  failures: ReturnType<typeof projectFailureSummary>;
  timeline: ReturnType<typeof projectTimeline>;
  summary: ReturnType<typeof rebuildRunSummary>;
  projection: ReturnType<typeof buildDurableProjection>;
  apply_state: "not_applied";
}

const DEMO_PLAN = `
\`\`\`yaml waygent-task
id: task_demo
title: Demo task
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`;

export async function runWaygent(options: RunWaygentOptions): Promise<WaygentRunResult> {
  const runId = options.run_id ?? "run_demo";
  const paths = runPaths(options.root, runId);
  if (hasExistingRunEvidence(paths)) {
    throw new Error("run_id_already_exists");
  }
  const profile = resolveExecutionProfile(options.profile, { provider: "fake" });
  const providerProfile = providerProfileRecord(profile);
  const planInput = resolveRunPlanInput(options);
  const parsed = parseWaygentPlan(planInput.markdown);
  const graph = buildTaskGraphFromPlan(parsed);
  const projection = buildDurableProjection(graph);
  const safeWave = projection.safe_wave.length > 0 ? projection.safe_wave : parsed.tasks[0] ? [parsed.tasks[0].id] : [];
  if (safeWave.length === 0) throw new Error("run requires at least one task");
  const firstTaskId = safeWave[0]!;
  const firstTask = graph.tasks.get(firstTaskId);
  if (!firstTask) throw new Error(`task ${firstTaskId} missing from graph`);
  const workspace = options.workspace ?? process.cwd();
  const preflight = classifySourceCheckout(workspace, parsed.tasks.flatMap((task) => task.file_claims));
  const worktreeRoot = options.worktree_root ?? join(options.root, "worktrees");
  const plannedWorktree = planWorktree({
    run_id: runId,
    task_id: firstTask.id,
    workspace,
    worktree_root: worktreeRoot
  });
  const startedAt = new Date().toISOString();
  const initialState: WaygentRunStateV2 = {
    schema: "waygent.run_state.v2",
    run_id: runId,
    workspace,
    source_branch: null,
    worktree_root: worktreeRoot,
    run_root: paths.root,
    artifact_root: paths.artifacts,
    state_path: join(paths.root, "state.json"),
    event_journal_path: paths.events,
    plan_path: planInput.path,
    spec_path: options.spec ?? null,
    provider_profile: providerProfile,
    status: "running",
    lifecycle_outcome: null,
    current_phase: "preflight",
    preflight,
    worktrees: [],
    tasks: Object.fromEntries(parsed.tasks.map((candidate) => [candidate.id, {
      id: candidate.id,
      status: safeWave.includes(candidate.id) ? "ready" : "pending",
      risk: candidate.risk,
      dependencies: candidate.dependencies,
      file_claims: candidate.file_claims,
      attempts: [],
      task_packet_path: null,
      task_packet_sha256: null,
      unit_manifest: {
        allowed_write_globs: candidate.file_claims.filter((claim) => claim.mode !== "read_only").map((claim) => claim.path),
        forbidden_write_globs: [".git/**", "node_modules/**"]
      },
      checkpoint_refs: [],
      latest_failure_class: null,
      decision_packet_ref: null,
      timing: {}
    }])),
    safe_waves: [{ wave_id: "wave_1", ready: safeWave, withheld: projection.withheld_tasks }],
    provider_attempts: [],
    reviews: [],
    verification: [],
    recovery: [],
    apply: { status: "not_applied" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: null,
    timestamps: { started_at: startedAt, updated_at: startedAt, completed_at: null }
  };
  const context = createRunExecutionContext({ root: options.root, state: initialState, next_sequence: 1 });
  context.flushState();

  context.appendEvent((sequence) => buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "platform.run_started",
    phase: "platform",
    outcome: "running",
    summary: "Run opened.",
    payload: { plan: planInput.path ?? options.plan, spec: options.spec, profile: providerProfile }
  }));
  context.appendEvent((sequence) => buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "runway.plan_loaded",
    phase: "plan",
    outcome: "success",
    summary: "Plan parsed into task graph.",
    payload: { task_count: parsed.tasks.length, profile: providerProfile, worktree: plannedWorktree }
  }));
  context.appendEvent((sequence) => ({
    ...buildRunEvent({
      run_id: runId,
      sequence,
      event_type: "runway.preflight_result",
      phase: "preflight",
      outcome: preflight.status === "dirty_related" ? "blocked" : "success",
      summary: preflight.status === "clean"
        ? "Source checkout preflight passed."
        : preflight.status === "dirty_unrelated"
          ? "Source checkout preflight found unrelated dirty files and continued."
          : "Source checkout preflight blocked dispatch.",
      payload: { ...preflight },
      trust_impact: preflight.status === "clean" ? "supports_success" : "neutral"
    }),
    ...(preflight.status === "dirty_unrelated" ? { severity: "warning" as const } : {})
  }));

  if (preflight.status === "dirty_related") {
    context.mutateState((state) => {
      state.status = "blocked";
      state.lifecycle_outcome = "blocked";
      state.current_phase = "preflight";
      state.apply = { status: "blocked", reason: "dirty_source_checkout" };
      for (const taskId of safeWave) {
        const task = state.tasks[taskId];
        if (task) {
          task.status = "blocked";
          task.latest_failure_class = "dirty_source_checkout";
        }
      }
      state.timestamps.completed_at = new Date().toISOString();
    });
    context.flushState();
    return finalizeRun(options.root, paths, runId, projection, context.nextSequence());
  }

  context.appendEvent((sequence) => buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "runway.safe_wave_selected",
    phase: "schedule",
    outcome: "success",
    summary: "Safe wave selected.",
    payload: { safe_wave: projection.safe_wave, wave_id: "wave_1" }
  }));

  let activeSafeWave = safeWave;
  let waveIndex = 1;
  while (activeSafeWave.length > 0) {
    const waveId = `wave_${waveIndex}`;
    const waveStarted = new Date().toISOString();
    const waveStartMs = performance.now();
    const concurrency = resolveWaveConcurrency({
      provider: profile.provider,
      safe_wave_size: activeSafeWave.length,
      env: process.env
    });
    context.mutateState((state) => {
      state.current_phase = "dispatch";
      for (const taskId of activeSafeWave) {
        const stateTask = state.tasks[taskId];
        if (stateTask) {
          stateTask.status = "running";
          stateTask.timing.started = waveStarted;
        }
      }
    });
    context.flushState();
    const resolvedProviderProcesses = resolveProviderProcesses(profile, options.provider_processes);
    const results = await executeBoundedSafeWave({
      task_ids: activeSafeWave,
      concurrency,
      execute: (taskId) => {
        const task = graph.tasks.get(taskId);
        if (!task) throw new Error(`task ${taskId} missing from graph`);
        const parsedTask = parsed.tasks.find((candidate) => candidate.id === task.id);
        if (!parsedTask) throw new Error(`task ${task.id} missing from parsed plan`);
        return executeWaygentTask({
          root: options.root,
          run_id: runId,
          workspace,
          worktree_root: worktreeRoot,
          task: parsedTask,
          checkpoint_inputs: dependencyCheckpointInputs(context.state, task.dependencies),
          spec: options.spec ?? null,
          provider: profile.provider,
          ...(Object.keys(resolvedProviderProcesses).length > 0 ? { provider_processes: resolvedProviderProcesses } : {})
        });
      }
    });
    for (const waveResult of results) {
      const task = graph.tasks.get(waveResult.task_id);
      if (waveResult.status === "rejected") {
        replayTaskExecutionFailure(context, waveResult.task_id, waveResult.error);
        if (task) {
          task.status = "FAILED_TERMINAL";
          task.latest_failure_class = "adapter_crashed";
        }
        continue;
      }
      replayTaskExecutionResult(context, waveResult.result);
      if (task && waveResult.result.status === "verified" && waveResult.result.checkpoint_refs[0]) {
        task.status = "APPLIED";
        task.checkpoint_ref = waveResult.result.checkpoint_refs[0];
      } else if (task) {
        task.status = "FAILED_TERMINAL";
        task.latest_failure_class = waveResult.result.latest_failure_class ?? "verification_failed";
      }
    }
    recordWaveTiming(context, {
      wave_id: waveId,
      concurrency,
      started: waveStarted,
      completed: new Date().toISOString(),
      duration_ms: Math.round(performance.now() - waveStartMs)
    });
    context.flushState();
    waveIndex += 1;
    const nextProjection = buildDurableProjection(graph);
    activeSafeWave = nextProjection.safe_wave;
    if (activeSafeWave.length === 0) break;
    context.appendEvent((sequence) => buildRunEvent({
      run_id: runId,
      sequence,
      event_type: "runway.safe_wave_selected",
      phase: "schedule",
      outcome: "success",
      summary: "Safe wave selected.",
      payload: { safe_wave: activeSafeWave, wave_id: `wave_${waveIndex}` }
    }));
    context.mutateState((state) => {
      state.safe_waves.push({ wave_id: `wave_${waveIndex}`, ready: activeSafeWave, withheld: nextProjection.withheld_tasks });
      for (const taskId of activeSafeWave) {
        const stateTask = state.tasks[taskId];
        if (stateTask) stateTask.status = "ready";
      }
    });
    context.flushState();
  }

  let completionAuditStatus = "failed";
  context.mutateState((state) => {
    state.current_phase = "complete";
    const verifiedCheckpointRefs = Object.values(state.tasks)
      .filter((task) => task.status === "verified")
      .flatMap((task) => task.checkpoint_refs);
    const allVerifiedTasksHaveCheckpoints = Object.values(state.tasks)
      .filter((task) => task.status === "verified")
      .every((task) => task.checkpoint_refs.length > 0);
    const combinedApplyEvidence = verifiedCheckpointRefs.length > 0 && allVerifiedTasksHaveCheckpoints
      ? createCombinedCheckpointPatchArtifact({
        run_root: state.run_root,
        run_id: state.run_id,
        checkpoint_refs: verifiedCheckpointRefs,
        source: state.workspace
      })
      : undefined;
    state.completion_audit = buildCompletionAudit({
      state,
      required_checks: parsed.tasks.flatMap((task) => task.verification_commands.length > 0 ? task.verification_commands : ["printf hello"]),
      verification_evidence: state.verification,
      review_evidence: [],
      ...(combinedApplyEvidence ? { combined_apply_evidence: combinedApplyEvidence } : {}),
      prompt_to_artifact_checklist: [
        "task_packet_written",
        "provider_attempt_recorded",
        "kernel_verification_recorded",
        "checkpoint_artifact_recorded"
      ]
    });
    completionAuditStatus = String((state.completion_audit as { status?: string }).status ?? "failed");
    state.status = completionAuditStatus === "passed" ? "completed" : "blocked";
    state.lifecycle_outcome = completionAuditStatus === "passed" ? "finished" : "blocked";
    state.timestamps.updated_at = new Date().toISOString();
    state.timestamps.completed_at = state.timestamps.updated_at;
  });
  context.flushState();
  const trust = projectTrustReport(readEvents(paths.events));
  context.appendEvent((sequence) => buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "lens.trust_report_updated",
    phase: "lens",
    outcome: "success",
    summary: "Trust report updated.",
    payload: { trust_status: trust.trust_status }
  }));
  const reconciliation = reconcileRunState(options.root, runId);
  context.mutateState((state) => {
    state.completion_audit = {
      ...(state.completion_audit ?? {}),
      state_reconciliation: reconciliation,
      status: completionAuditStatus === "passed" && reconciliation.passed ? "passed" : "failed"
    };
    if (!reconciliation.passed) {
      state.status = "blocked";
      state.lifecycle_outcome = "blocked";
    }
    state.timestamps.updated_at = new Date().toISOString();
  });
  context.flushState();
  return finalizeRun(options.root, paths, runId, projection, context.nextSequence());
}

function hasExistingRunEvidence(paths: ReturnType<typeof runPaths>): boolean {
  return existsSync(paths.root) || existsSync(join(paths.root, "state.json")) || existsSync(paths.events);
}

function finalizeRun(
  root: string,
  paths: ReturnType<typeof runPaths>,
  runId: string,
  projection: ReturnType<typeof buildDurableProjection>,
  sequence: number
): WaygentRunResult {
  const existingEvents = readEvents(paths.events);
  if (!existingEvents.some((event) => event.event_type === "lens.trust_report_updated")) {
    const trust = projectTrustReport(existingEvents);
    appendEvent(paths.events, buildRunEvent({
      run_id: runId,
      sequence,
      event_type: "lens.trust_report_updated",
      phase: "lens",
      outcome: "success",
      summary: "Trust report updated.",
      payload: { trust_status: trust.trust_status }
    }));
  }
  writeLatestRunId(root, runId);

  const events = readEvents(paths.events);
  return {
    run_id: runId,
    events,
    trust_report: projectTrustReport(events),
    failures: projectFailureSummary(events),
    timeline: projectTimeline(events),
    summary: rebuildRunSummary(events),
    projection,
    apply_state: "not_applied"
  };
}

function replayTaskExecutionResult(context: RunExecutionContext, result: WaygentTaskExecutionResult): void {
  context.mutateState((state) => {
    state.current_phase = "verify";
    state.provider_attempts = [...state.provider_attempts, result.provider_attempt];
    state.verification = [...state.verification, ...result.verification_records];
    state.worktrees = [
      ...(state.worktrees ?? []).filter((item) => item.task_id !== result.task_id),
      result.worktree_manifest
    ];
    const task = state.tasks[result.task_id];
    if (task) {
      task.status = result.status;
      task.task_packet_path = result.task_packet_path;
      task.task_packet_sha256 = result.task_packet_sha256;
      task.attempts = [...new Set([...task.attempts, result.provider_attempt.attempt_id])];
      task.latest_failure_class = result.latest_failure_class;
      task.checkpoint_refs = result.checkpoint_refs;
      task.timing.started = result.timing.started;
      task.timing.completed = result.timing.completed;
      task.timing.duration_ms = String(result.timing.duration_ms);
    }
  });
  for (const event of result.events) {
    context.appendEvent((sequence) => buildRunEvent({ ...event, sequence }));
  }
}

function replayTaskExecutionFailure(context: RunExecutionContext, taskId: string, error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  context.mutateState((state) => {
    state.current_phase = "verify";
    const task = state.tasks[taskId];
    if (task) {
      task.status = "blocked";
      task.latest_failure_class = "adapter_crashed";
      task.timing.completed = new Date().toISOString();
    }
  });
  context.appendEvent((sequence) => buildRunEvent({
    run_id: context.run_id,
    sequence,
    event_type: "runway.worker_result",
    phase: "worker",
    outcome: "failed",
    summary: "Task execution failed before durable worker evidence was produced.",
    payload: {
      task_id: taskId,
      failure_class: "adapter_crashed",
      error: message
    },
    trust_impact: "supports_failure"
  }));
}

function recordWaveTiming(
  context: RunExecutionContext,
  timing: { wave_id: string; concurrency: number; started: string; completed: string; duration_ms: number }
): void {
  context.mutateState((state) => {
    const wave = state.safe_waves.find((item) => item.wave_id === timing.wave_id) as
      | (WaygentRunStateV2["safe_waves"][number] & {
        concurrency?: number;
        timing?: { started: string; completed: string; duration_ms: number };
      })
      | undefined;
    if (!wave) return;
    wave.concurrency = timing.concurrency;
    wave.timing = {
      started: timing.started,
      completed: timing.completed,
      duration_ms: timing.duration_ms
    };
  });
}

function providerProfileRecord(profile: ReturnType<typeof resolveExecutionProfile>): Record<string, unknown> {
  return {
    provider: profile.provider,
    execution_mode: profile.execution_mode,
    main: { ...profile.main },
    subagent: { ...profile.subagent },
    evidence_event_type: profile.evidence_event_type
  };
}

export function resolveProviderProcesses(
  profile: ExecutionProfile,
  overrides: Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>> | undefined
): Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>> {
  const result: Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>> = {};
  if (overrides?.codex) result.codex = overrides.codex;
  if (profile.provider === "claude") {
    const userClaude = overrides?.claude;
    result.claude = {
      executable: userClaude?.executable ?? "claude",
      args: userClaude?.args ?? ["-p", "--output-format", "json"],
      ...(userClaude?.cwd ? { cwd: userClaude.cwd } : {}),
      ...(userClaude?.env ? { env: userClaude.env } : {}),
      ...(userClaude?.timeout_ms ? { timeout_ms: userClaude.timeout_ms } : {}),
      model: userClaude?.model ?? profile.subagent.model,
      effort: userClaude?.effort ?? profile.subagent.reasoning
    };
  } else if (overrides?.claude) {
    result.claude = overrides.claude;
  }
  return result;
}

export async function runWaygentDemo(options: RunWaygentOptions): Promise<WaygentRunResult> {
  return runWaygent({ ...options, plan: options.plan ?? DEMO_PLAN });
}

export function defaultRunRoot(): string {
  return join(tmpdir(), "waygent-runs");
}

function resolveRunPlanInput(options: RunWaygentOptions): { markdown: string; path: string | null } {
  if (options.plan_path || options.latest || options.topic) {
    const discoveryOptions: Parameters<typeof resolvePlanInput>[0] = {
      workspace: options.workspace ?? process.cwd()
    };
    if (options.plan_path) discoveryOptions.plan_path = options.plan_path;
    if (options.latest) discoveryOptions.latest = options.latest;
    if (options.topic) discoveryOptions.topic = options.topic;
    if (options.plan) discoveryOptions.inline_plan = options.plan;
    return resolvePlanInput(discoveryOptions);
  }
  return { markdown: options.plan ?? DEMO_PLAN, path: null };
}

function dependencyCheckpointInputs(state: WaygentRunStateV2, dependencies: string[]): string[] {
  return dependencies.flatMap((dependency) => state.tasks[dependency]?.checkpoint_refs ?? []);
}
