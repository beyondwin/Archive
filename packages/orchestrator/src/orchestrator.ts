import { existsSync, readFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import type { AgentLensEvent, ArtifactIndexEntry, FailureClass, IntakeFinding, ProviderAttempt, ProviderProcessEvidence, ReviewResult, WaygentIntakeRecovery, WaygentRunStateV2, WorkerResult } from "@waygent/contracts";
import { planWorktree } from "@waygent/kernel-client";
import { projectFailureSummary, projectTimeline, projectTrustReport } from "@waygent/lens-projectors";
import { appendEvent, readEvents, rebuildRunSummary, runPaths, writeArtifact, writeLatestRunId } from "@waygent/lens-store";
import {
  attestProviderProcessOptions,
  ClaudeProviderAdapter,
  CodexProviderAdapter,
  FakeProviderAdapter,
  probeProviderHelp,
  type ProviderAdapter,
  type ProviderAdapterRunResult,
  type ProviderCapabilityAttestation,
  type ProviderProcessOptions
} from "@waygent/provider-adapters";
import { buildDurableProjection, type TaskGraph } from "@waygent/runway-control";
import { auditAdjacentContracts } from "./adjacentContractAudit";
import { applyExecutionDependencyBarriers } from "./executionDependencyBarrier";
import { artifactIndexEntry, mergeArtifactIndex } from "./artifactIndex";
import { createCombinedCheckpointPatchArtifact, type CombinedCheckpointPatchResult } from "./checkpointArtifacts";
import { buildCompletionAudit } from "./completionAudit";
import { createEmptyCostLedger, recordProviderAttemptCost, shouldPauseForBudget, shouldWarnForBudget, type BudgetPolicy } from "./costLedger";
import { appendDecisionFromWorker, packetDecisionSummaries, writeDecisionsProjection } from "./decisions";
import { resolveExecutionProfile, roleProfileFor, type ExecutionProfile, type ProfileOverride, type ProviderName, type WorkerRoleSlot } from "./executionProfile";
import { recoverWaygentPlanInput } from "./intakeRecovery";
import { captureWorktreePatch } from "./patchCapture";
import { selectRepairAction } from "./recoveryExecutor";
import { prepareRepairWorktree } from "./repairDispatch";
import { buildRepairPacket, type RepairPacketVerificationInput } from "./repairPacket";
import { resolvePlanInput, resolveSpecInput } from "./planDiscovery";
import { normalizeWaygentPlanInput } from "./planNormalizer";
import { parseWaygentPlan } from "./planParser";
import { extractSuperpowersPlan } from "./planAdapters/planClaimExtraction";
import { buildProjectScriptCatalog } from "./planAdapters/projectScriptCatalog";
import { classifyVerificationCommand } from "./planAdapters/verificationPolicy";
import { runPlanPreflight, type PlanPreflightMode } from "./planPreflight";
import { buildRunEvent } from "./runEvents";
import { createRunExecutionContext, type RunExecutionContext } from "./runExecutionContext";
import { readRunStateV2 } from "./runState";
import { classifySourceCheckout } from "./sourceCheckout";
import { deriveRunId, RUN_ID_COLLISION_MAX_RETRIES } from "./runIdDerivation";
import { reconcileRunState } from "./stateReconciliation";
import { buildTaskGraphFromPlan } from "./taskGraph";
import { executeBoundedSafeWave, resolveWaveConcurrency } from "./safeWaveExecutor";
import { appendSchedulerRecovery } from "./taskRecovery";
import { executeWaygentTask, type WaygentTaskExecutionResult } from "./taskExecutor";
import { taskRequiresCheckpoint } from "./taskCheckpointPolicy";
import { evaluateTerminalCompletionInvariant } from "./terminalInvariant";
import { buildSpecManifest, specSliceForTask } from "@waygent/context-packer";

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
  plan_preflight?: PlanPreflightMode;
  spec_slice?: "off" | "manifest";
  budget_cap_usd?: number | null;
  budget_action?: "warn" | "pause" | "off";
  hook_config?: "off" | "builtin" | string;
  require_method_evidence?: boolean;
  initial_reviews?: ReviewResult[];
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
  const { runId, paths } = resolveRunIdAndPaths(options);
  const workspace = options.workspace ?? process.cwd();
  const profile = resolveExecutionProfile(options.profile, { provider: "fake" });
  const providerProfile = providerProfileRecord(profile);
  const planInput = resolveRunPlanInput({ ...options, workspace });
  const specInput = resolveSpecInput({
    workspace,
    ...(options.spec !== undefined ? { spec: options.spec } : {})
  });
  const worktreeRoot = options.worktree_root ?? join(options.root, "worktrees");
  const extractedPlan = extractSuperpowersPlan(planInput.markdown);
  const extractionCatalog = buildProjectScriptCatalog(workspace);
  const extractReport = {
    tasks: extractedPlan.tasks.map((task) => ({
      number: task.number,
      title: task.title,
      explicit_file_claims: task.explicit_file_claims,
      prose_file_claims: task.prose_file_claims,
      fenced_commands: task.fenced_commands,
      fenced_examples: (task.fenced_examples ?? []).map((block) => ({
        language: block.language,
        source: block.source,
        content: block.content,
        line_start: block.line_start,
        line_end: block.line_end
      })),
      command_candidates: (task.command_candidates ?? []).map((candidate) => ({
        ...candidate,
        classification: classifyVerificationCommand({ command: candidate.command, workspace, catalog: extractionCatalog })
      })),
      verification: task.fenced_commands.map((command) =>
        classifyVerificationCommand({ command, workspace, catalog: extractionCatalog })
      )
    }))
  };
  const contractAuditFindings = auditAdjacentContracts({
    plan_markdown: planInput.markdown,
    spec_markdown: specInput.markdown,
    file_claims: extractedPlan.tasks.flatMap((task) => [
      ...task.explicit_file_claims.map((claim) => claim.path),
      ...task.prose_file_claims.map((claim) => claim.path)
    ])
  });
  const recovered = recoverWaygentPlanInput({
    markdown: planInput.markdown,
    path: planInput.path,
    workspace,
    spec_markdown: specInput.markdown,
    spec_path: specInput.path
  });
  if (recovered.status === "decision_required" || recovered.status === "failed") {
    return finalizeIntakeBlockedRun({
      options,
      paths,
      runId,
      workspace,
      worktreeRoot,
      planInput,
      specInput,
      providerProfile,
      intakeRecovery: recovered.report,
      extractReport,
      adjacentContractFindings: contractAuditFindings
    });
  }
  const normalizedPlan = recovered.normalized_plan;
  const planPreflightMode = options.plan_preflight ?? (profile.provider === "fake" ? "deterministic" : "off");
  const planPreflight = runPlanPreflight({
    workspace,
    plan_path: planInput.path,
    normalized_plan: normalizedPlan,
    spec_path: specInput.path
  }, planPreflightMode);
  if (planPreflight.status === "failed") {
    throw new Error(`plan_preflight_failed:\n${planPreflight.errors.map((error) => `- ${error}`).join("\n")}`);
  }
  const normalizedPlanArtifact = normalizedPlan.mode === "superpowers"
    ? writeArtifact(paths.root, "plan/normalized-waygent-plan.md", `${normalizedPlan.markdown.trimEnd()}\n`, "text/markdown")
    : null;
  const parsedBeforeBarriers = parseWaygentPlan(normalizedPlan.markdown);
  const barrierResult = applyExecutionDependencyBarriers(parsedBeforeBarriers);
  const parsed = barrierResult.plan;
  const specManifest = options.spec_slice === "off"
    ? undefined
    : buildSpecManifest({
      spec: specInput.markdown,
      spec_path: specInput.path,
      tasks: parsed.tasks.map((task) => ({ id: task.id, title: task.title, instructions: task.instructions }))
    });
  const graph = buildTaskGraphFromPlan(parsed);
  const projection = buildDurableProjection(graph);
  const safeWave = projection.safe_wave.length > 0 ? projection.safe_wave : parsed.tasks[0] ? [parsed.tasks[0].id] : [];
  if (safeWave.length === 0) throw new Error("run requires at least one task");
  const firstTaskId = safeWave[0]!;
  const firstTask = graph.tasks.get(firstTaskId);
  if (!firstTask) throw new Error(`task ${firstTaskId} missing from graph`);
  const preflight = classifySourceCheckout(workspace, parsed.tasks.flatMap((task) => task.file_claims));
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
    spec_path: specInput.path,
    provider_profile: providerProfile,
    ...(recovered.status === "recovered" ? { intake_recovery: recovered.report } : {}),
    decisions_register: [],
    ...(specManifest ? { spec_manifest: specManifest } : {}),
    cost_ledger: createEmptyCostLedger(),
    budget_cap_usd: options.budget_cap_usd ?? null,
    budget_action: options.budget_action ?? "off",
    method_evidence_required: options.require_method_evidence ?? false,
    hook_config: options.hook_config ?? "builtin",
    status: "running",
    lifecycle_outcome: null,
    current_phase: "preflight",
    preflight,
    worktrees: [],
    artifact_index: [],
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
    reviews: options.initial_reviews ?? [],
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
    payload: {
      plan: planInput.path ?? options.plan,
      spec: specInput.path ?? options.spec,
      profile: providerProfile,
      plan_normalization: planNormalizationPayload(normalizedPlan, normalizedPlanArtifact?.path ?? null)
    }
  }));
  const extractReportArtifact = writeArtifact(
    paths.root,
    "intake/extract-report.json",
    `${JSON.stringify(extractReport, null, 2)}\n`,
    "application/json"
  );
  context.appendEvent((sequence) => buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "platform.intake_extract_completed",
    phase: "intake",
    outcome: "success",
    summary: "Plan intake extraction completed.",
    payload: {
      extract_report_ref: extractReportArtifact.path,
      task_count: extractedPlan.tasks.length,
      adjacent_contract_findings: contractAuditFindings
    },
    trust_impact: contractAuditFindings.length > 0 ? "requires_review" : "neutral"
  }));
  context.appendEvent((sequence) => buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "platform.plan_preflight_completed",
    phase: "preflight",
    outcome: planPreflight.status === "passed" || planPreflight.status === "skipped" ? "success" : "blocked",
    summary: planPreflight.status === "skipped" ? "Plan/spec preflight skipped." : "Plan/spec preflight completed.",
    payload: { ...planPreflight },
    trust_impact: planPreflight.status === "skipped" ? "neutral" : "supports_success"
  }));
  context.appendEvent((sequence) => buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "runway.plan_loaded",
    phase: "plan",
    outcome: "success",
    summary: "Plan parsed into task graph.",
    payload: {
      task_count: parsed.tasks.length,
      profile: providerProfile,
      worktree: plannedWorktree,
      plan_normalization: planNormalizationPayload(normalizedPlan, normalizedPlanArtifact?.path ?? null)
    }
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

  for (const barrier of barrierResult.barriers) {
    context.appendEvent((sequence) => buildRunEvent({
      run_id: runId,
      sequence,
      event_type: "runway.wave_barrier_inserted",
      phase: "schedule",
      outcome: "success",
      summary: "Execution dependency barrier inserted.",
      payload: barrier as unknown as Record<string, unknown>,
      trust_impact: "requires_review"
    }));
  }

  const resolvedProviderProcessesBase = resolveProviderProcesses(profile, options.provider_processes);
  const providerCapabilityAttestations: ProviderCapabilityAttestation[] = [];
  const attestedProviderProcesses: typeof resolvedProviderProcessesBase = { ...resolvedProviderProcessesBase };
  if (profile.provider === "codex" && resolvedProviderProcessesBase.codex) {
    const attested = attestProviderProcessOptions(
      "codex",
      resolvedProviderProcessesBase.codex,
      probeProviderHelp("codex", resolvedProviderProcessesBase.codex)
    );
    attestedProviderProcesses.codex = attested.options;
    providerCapabilityAttestations.push(attested.capability);
  }
  if (profile.provider === "claude" && resolvedProviderProcessesBase.claude) {
    const attested = attestProviderProcessOptions(
      "claude",
      resolvedProviderProcessesBase.claude,
      probeProviderHelp("claude", resolvedProviderProcessesBase.claude)
    );
    attestedProviderProcesses.claude = attested.options;
    providerCapabilityAttestations.push(attested.capability);
  }
  if (providerCapabilityAttestations.length > 0) {
    const capabilityArtifact = writeArtifact(
      paths.root,
      "platform/provider-capabilities.json",
      `${JSON.stringify({ provider_capabilities: providerCapabilityAttestations }, null, 2)}\n`,
      "application/json"
    );
    context.appendEvent((sequence) => buildRunEvent({
      run_id: runId,
      sequence,
      event_type: "platform.provider_capability_attested",
      phase: "platform",
      outcome: "success",
      summary: "Provider CLI capability attested.",
      payload: {
        provider_capabilities_ref: capabilityArtifact.path,
        provider_capabilities: providerCapabilityAttestations
      },
      trust_impact: providerCapabilityAttestations.some((item) => item.reason !== "supported") ? "requires_review" : "neutral"
    }));
  }

  let activeSafeWave = safeWave;
  let waveIndex = 1;
  const codexResumeSessions = new Map<string, string>();
  while (activeSafeWave.length > 0) {
    const waveId = `wave_${waveIndex}`;
    if (shouldPauseForBudget(context.state.cost_ledger, budgetPolicyFromState(context.state))) {
      pauseRunForBudget(context, activeSafeWave);
      break;
    }
    if (shouldWarnForBudget(context.state.cost_ledger, budgetPolicyFromState(context.state))) {
      context.appendEvent((sequence) => buildRunEvent({
        run_id: runId,
        sequence,
        event_type: "platform.cost_budget_warning",
        phase: "cost",
        outcome: "success",
        summary: "Cost budget warning threshold exceeded.",
        payload: { cost_ledger: context.state.cost_ledger, budget_cap_usd: context.state.budget_cap_usd },
        trust_impact: "requires_review"
      }));
    }
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
    const resolvedProviderProcesses = attestedProviderProcesses;
    const results = await executeBoundedSafeWave({
      task_ids: activeSafeWave,
      concurrency,
      execute: (taskId) => {
        const task = graph.tasks.get(taskId);
        if (!task) throw new Error(`task ${taskId} missing from graph`);
        const parsedTask = parsed.tasks.find((candidate) => candidate.id === task.id);
        if (!parsedTask) throw new Error(`task ${task.id} missing from parsed plan`);
        const slice = specSliceForTask(specInput.markdown, specManifest, task.id);
        context.appendEvent((sequence) => buildRunEvent({
          run_id: runId,
          sequence,
          event_type: "runway.spec_slice_computed",
          phase: "context",
          outcome: "success",
          summary: slice.fallback_used ? "Spec slice fell back to full spec." : "Spec slice computed for task.",
          payload: {
            task_id: task.id,
            sections_used: slice.sections_used,
            slice_bytes: slice.slice_bytes,
            fallback_used: slice.fallback_used,
            fallback_reason: slice.fallback_reason
          },
          trust_impact: "neutral"
        }));
        const dispatchRole: WorkerRoleSlot = "implement";
        const roleAwareProcesses = applyRoleRoutingToProcesses(resolvedProviderProcesses, profile, dispatchRole);
        const codexResume = codexResumeSessions.get(task.id);
        const processesWithResume = applyCodexResumeContext(roleAwareProcesses, codexResume);
        return executeWaygentTask({
          root: options.root,
          run_id: runId,
          workspace,
          worktree_root: worktreeRoot,
          task: parsedTask,
          checkpoint_inputs: dependencyCheckpointInputs(context.state, task.dependencies),
          spec: slice.text,
          provider: profile.provider,
          decisions: packetDecisionSummaries(context.state),
          requested_model: requestedModelForProfile(profile, dispatchRole),
          hooks_enabled: options.hook_config !== "off",
          attempt: (task.retry_count ?? 0) + 1,
          ...(Object.keys(processesWithResume).length > 0 ? { provider_processes: processesWithResume } : {})
        });
      }
    });
    for (const waveResult of results) {
      const task = graph.tasks.get(waveResult.task_id);
      if (waveResult.status === "rejected") {
        replayTaskExecutionFailure(context, waveResult.task_id, waveResult.error);
        const recovery = recordTaskRecovery(context, {
          task_id: waveResult.task_id,
          failure_class: "adapter_crashed",
          prior_summary: errorSummary(waveResult.error),
          evidence_refs: []
        });
        if (task) {
          if (isRetryRecoveryAction(recovery.decision.action)) {
            task.status = "READY";
            task.retry_count = (task.retry_count ?? 0) + 1;
            delete task.latest_failure_class;
            markStateTaskReadyForRetry(context, task.id, "adapter_crashed");
          } else {
            task.status = "FAILED_TERMINAL";
            task.latest_failure_class = "adapter_crashed";
          }
        }
        continue;
      }
      replayTaskExecutionResult(context, waveResult.result);
      recordRuntimeEvidence(context, waveResult.result);
      capturePatchForWorkerAttempt(context, waveResult.result, paths.root);
      const capturedSessionId = extractSessionIdFromWorker(waveResult.result.worker_result);
      if (profile.provider === "codex" && capturedSessionId) {
        codexResumeSessions.set(waveResult.task_id, capturedSessionId);
      }
      if (task && waveResult.result.status === "verified") {
        task.status = "APPLIED";
        if (waveResult.result.checkpoint_refs[0]) task.checkpoint_ref = waveResult.result.checkpoint_refs[0];
      } else if (task) {
        const failureClass = waveResult.result.latest_failure_class ?? "verification_failed";
        const priorWorker = waveResult.result.worker_result;
        const repairBudget = context.state.repair_budget?.[waveResult.task_id] ?? { max_attempts: 2, current: 0 };
        const repair = selectRepairAction({
          failure_class: failureClass,
          prior_worker_result: priorWorker,
          repair_budget: repairBudget
        });
        if (repair && repair.action === "dispatch_repair") {
          const dispatched = await runRepairAttempt({
            context,
            run_id: runId,
            paths,
            workspace,
            worktree_root: worktreeRoot,
            task_id: waveResult.task_id,
            prior_result: waveResult.result,
            repair,
            profile,
            provider_processes: attestedProviderProcesses,
            task_file_claims: task?.file_claims ?? []
          });
          if (dispatched.status === "dispatched") {
            if (task) {
              task.status = "READY";
              task.retry_count = (task.retry_count ?? 0) + 1;
              delete task.latest_failure_class;
              markStateTaskReadyForRetry(context, task.id, "verification_failed");
            }
            context.flushState();
            continue;
          }
          // dispatch blocked — fall through to existing recovery path
        }
        const recovery = recordTaskRecovery(context, {
          task_id: waveResult.result.task_id,
          failure_class: failureClass,
          prior_summary: waveResult.result.worker_result.summary,
          evidence_refs: taskRecoveryEvidenceRefs(waveResult.result)
        });
        if (isRetryRecoveryAction(recovery.decision.action)) {
          task.status = "READY";
          task.retry_count = (task.retry_count ?? 0) + 1;
          delete task.latest_failure_class;
          markStateTaskReadyForRetry(context, task.id, failureClass);
        } else {
          task.status = "FAILED_TERMINAL";
          task.latest_failure_class = failureClass;
        }
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
    if (shouldPauseForBudget(context.state.cost_ledger, budgetPolicyFromState(context.state))) {
      pauseRunForBudget(context, activeSafeWave);
      context.flushState();
      break;
    }
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
  writeDecisionsProjection(paths.root, runId, context.state.decisions_register ?? []);
  context.mutateState((state) => {
    state.current_phase = "complete";
    const checkpointedTasks = Object.values(state.tasks)
      .filter((task) => task.status === "verified" && taskRequiresCheckpoint(task));
    const verifiedCheckpointRefs = checkpointedTasks
      .flatMap((task) => task.checkpoint_refs);
    const allVerifiedTasksHaveCheckpoints = checkpointedTasks
      .every((task) => task.checkpoint_refs.length > 0);
    const combinedApplyEvidence = verifiedCheckpointRefs.length > 0 && allVerifiedTasksHaveCheckpoints
      ? createCombinedCheckpointPatchArtifact({
        run_root: state.run_root,
        run_id: state.run_id,
        checkpoint_refs: verifiedCheckpointRefs,
        source: state.workspace
      })
      : undefined;
    state.artifact_index = mergeArtifactIndex(state.artifact_index, combinedApplyArtifactEntries(combinedApplyEvidence));
    const reviewEvidence = state.reviews.map((review) => ({
      task_id: review.task_id,
      attempt_id: review.attempt_id,
      verdict: review.verdict,
      spec_score: review.spec_score,
      quality_score: review.quality_score,
      residual_risk: review.residual_risk
    }));
    state.completion_audit = buildCompletionAudit({
      state,
      required_checks: parsed.tasks.flatMap((task) => task.verification_commands.length > 0 ? task.verification_commands : ["printf hello"]),
      verification_evidence: state.verification,
      review_evidence: reviewEvidence,
      ...(combinedApplyEvidence ? { combined_apply_evidence: combinedApplyEvidence } : {}),
      prompt_to_artifact_checklist: [
        "task_packet_written",
        "provider_attempt_recorded",
        "kernel_verification_recorded",
        "checkpoint_artifact_recorded"
      ]
    });
    completionAuditStatus = String((state.completion_audit as { status?: string }).status ?? "failed");
    state.status = completionAuditStatus === "passed" ? "running" : "blocked";
    state.lifecycle_outcome = completionAuditStatus === "passed" ? null : "blocked";
    state.timestamps.updated_at = new Date().toISOString();
    state.timestamps.completed_at = completionAuditStatus === "passed" ? null : state.timestamps.updated_at;
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
  const reconciledDrift = readRunStateV2(options.root, runId).drift;
  context.mutateState((state) => {
    state.drift = reconciledDrift;
    const reconciliationResidualRisk = reconciliation.passed ? [] : ["state_reconciliation:blocking"];
    const auditResidualRisk = Array.isArray((state.completion_audit as { residual_risk?: unknown } | null)?.residual_risk)
      ? (state.completion_audit as { residual_risk: unknown[] }).residual_risk.map(String)
      : ["completion_audit:missing_residual_risk"];
    const candidateAuditStatus = completionAuditStatus === "passed" && reconciliation.passed ? "passed" : "failed";
    state.completion_audit = {
      ...(state.completion_audit ?? {}),
      state_reconciliation: reconciliation,
      status: candidateAuditStatus,
      residual_risk: [...new Set([...auditResidualRisk, ...reconciliationResidualRisk])]
    };
    const terminalInvariant = evaluateTerminalCompletionInvariant(state);
    const terminalResidualRisk = terminalInvariant.blockers.map((blocker) => `terminal_invariant:${blocker.code}`);
    const currentResidualRisk = Array.isArray((state.completion_audit as { residual_risk?: unknown } | null)?.residual_risk)
      ? (state.completion_audit as { residual_risk: unknown[] }).residual_risk.map(String)
      : [];
    state.completion_audit = {
      ...(state.completion_audit ?? {}),
      terminal_invariant: terminalInvariant,
      status: terminalInvariant.passed ? "passed" : "failed",
      residual_risk: terminalInvariant.passed ? [] : [...new Set([...currentResidualRisk, ...terminalResidualRisk])]
    };
    state.status = terminalInvariant.passed ? "completed" : "blocked";
    state.lifecycle_outcome = terminalInvariant.passed ? "finished" : "blocked";
    state.timestamps.completed_at = new Date().toISOString();
    state.timestamps.updated_at = new Date().toISOString();
  });
  context.flushState();
  return finalizeRun(options.root, paths, runId, projection, context.nextSequence());
}

function hasExistingRunEvidence(paths: ReturnType<typeof runPaths>): boolean {
  return existsSync(paths.root) || existsSync(join(paths.root, "state.json")) || existsSync(paths.events);
}

interface FinalizeIntakeBlockedRunInput {
  options: RunWaygentOptions;
  paths: ReturnType<typeof runPaths>;
  runId: string;
  workspace: string;
  worktreeRoot: string;
  planInput: { markdown: string; path: string | null };
  specInput: { markdown: string; path: string | null };
  providerProfile: Record<string, unknown>;
  intakeRecovery: WaygentIntakeRecovery;
  extractReport?: Record<string, unknown>;
  adjacentContractFindings?: IntakeFinding[];
}

function finalizeIntakeBlockedRun(input: FinalizeIntakeBlockedRunInput): WaygentRunResult {
  const { options, paths, runId, workspace, worktreeRoot, planInput, specInput, providerProfile, intakeRecovery } = input;
  const startedAt = new Date().toISOString();
  const extractArtifact = input.extractReport
    ? writeArtifact(
      paths.root,
      "intake/extract-report.json",
      `${JSON.stringify(input.extractReport, null, 2)}\n`,
      "application/json"
    )
    : null;
  writeArtifact(
    paths.root,
    "intake/recovery-report.json",
    `${JSON.stringify(intakeRecovery, null, 2)}\n`,
    "application/json"
  );
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
    spec_path: specInput.path,
    provider_profile: providerProfile,
    intake_recovery: intakeRecovery,
    decisions_register: [],
    cost_ledger: createEmptyCostLedger(),
    budget_cap_usd: options.budget_cap_usd ?? null,
    budget_action: options.budget_action ?? "off",
    method_evidence_required: options.require_method_evidence ?? false,
    hook_config: options.hook_config ?? "builtin",
    status: "blocked",
    lifecycle_outcome: "blocked",
    current_phase: "preflight",
    worktrees: [],
    artifact_index: [],
    tasks: {},
    safe_waves: [],
    provider_attempts: [],
    reviews: [],
    verification: [],
    recovery: [],
    apply: { status: "blocked", reason: "intake_decision_required" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: null,
    timestamps: { started_at: startedAt, updated_at: startedAt, completed_at: startedAt }
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
    payload: {
      plan: planInput.path ?? options.plan,
      spec: specInput.path ?? options.spec,
      profile: providerProfile
    }
  }));
  if (extractArtifact || input.extractReport) {
    const adjacentFindings = input.adjacentContractFindings ?? [];
    const taskCount = Array.isArray((input.extractReport as { tasks?: unknown[] } | undefined)?.tasks)
      ? ((input.extractReport as { tasks: unknown[] }).tasks).length
      : 0;
    context.appendEvent((sequence) => buildRunEvent({
      run_id: runId,
      sequence,
      event_type: "platform.intake_extract_completed",
      phase: "intake",
      outcome: "success",
      summary: "Plan intake extraction completed.",
      payload: {
        extract_report_ref: extractArtifact?.path ?? null,
        task_count: taskCount,
        adjacent_contract_findings: adjacentFindings
      },
      trust_impact: adjacentFindings.length > 0 ? "requires_review" : "neutral"
    }));
  }
  context.appendEvent((sequence) => buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "platform.intake_decision_required",
    phase: "intake",
    outcome: "blocked",
    summary: intakeRecovery.question ?? "Intake recovery requires a user decision before execution.",
    payload: { intake_recovery: intakeRecovery },
    trust_impact: "requires_review"
  }));
  const emptyProjection = buildDurableProjection({ tasks: new Map() } as TaskGraph);
  return finalizeRun(options.root, paths, runId, emptyProjection, context.nextSequence());
}

function resolveRunIdAndPaths(options: RunWaygentOptions): { runId: string; paths: ReturnType<typeof runPaths> } {
  if (options.run_id !== undefined) {
    const paths = runPaths(options.root, options.run_id);
    if (hasExistingRunEvidence(paths)) {
      throw new Error(
        `run_id_already_exists: ${options.run_id} (existing run at ${paths.root}). ` +
          `To start fresh, choose a different --run id, omit --run to let Waygent derive a unique one, ` +
          `or remove the existing run directory after confirming its evidence is no longer needed.`
      );
    }
    return { runId: options.run_id, paths };
  }
  const planPath = options.plan_path ?? null;
  const now = new Date();
  for (let suffix = 0; suffix <= RUN_ID_COLLISION_MAX_RETRIES; suffix += 1) {
    const candidate = deriveRunId({ plan_path: planPath, now, suffix });
    const paths = runPaths(options.root, candidate);
    if (!hasExistingRunEvidence(paths)) {
      return { runId: candidate, paths };
    }
  }
  throw new Error("run_id_collision_unresolved");
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
    state.artifact_index = mergeArtifactIndex(state.artifact_index, result.artifact_index_entries);
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
      task.phase_timings = result.phase_timings;
      task.model_used = result.provider_attempt.actual_model ? [result.provider_attempt.actual_model] : [];
      task.hook_retries = result.events.filter((event) => event.event_type === "kernel.hook_denied").length;
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

function recordRuntimeEvidence(context: RunExecutionContext, result: WaygentTaskExecutionResult): void {
  let decision: ReturnType<typeof appendDecisionFromWorker> = null;
  context.mutateState((state) => {
    state.cost_ledger = recordProviderAttemptCost(state.cost_ledger ?? createEmptyCostLedger(), {
      task_id: result.task_id,
      role: result.provider_attempt.role,
      usage: result.provider_attempt.usage ?? null,
      usage_source: result.provider_attempt.usage_source ?? "unknown",
      recorded_at: result.provider_attempt.completed_at ?? new Date().toISOString(),
      ...(result.provider_attempt.requested_model ? { requested_model: result.provider_attempt.requested_model } : {}),
      ...(result.provider_attempt.actual_model ? { actual_model: result.provider_attempt.actual_model } : {})
    });
    if (result.status === "verified") {
      decision = appendDecisionFromWorker(state, result.worker_result);
      writeDecisionsProjection(state.run_root, state.run_id, state.decisions_register ?? []);
    }
  });
  context.appendEvent((sequence) => buildRunEvent({
    run_id: context.run_id,
    sequence,
    event_type: "platform.cost_accumulated",
    phase: "cost",
    outcome: "success",
    summary: "Provider usage cost ledger updated.",
    payload: {
      task_id: result.task_id,
      attempt_id: result.provider_attempt.attempt_id,
      usage_source: result.provider_attempt.usage_source ?? "unknown",
      usage: result.provider_attempt.usage ?? null,
      actual_model: result.provider_attempt.actual_model ?? null
    },
    trust_impact: "neutral"
  }));
  if (decision) {
    context.appendEvent((sequence) => buildRunEvent({
      run_id: context.run_id,
      sequence,
      event_type: decision?.supersedes ? "runway.decision_superseded" : "runway.decision_appended",
      phase: "decision",
      outcome: "success",
      summary: "Runtime decision appended.",
      payload: { decision },
      trust_impact: "supports_success"
    }));
  }
}

function capturePatchForWorkerAttempt(
  context: RunExecutionContext,
  result: WaygentTaskExecutionResult,
  runRoot: string
): void {
  let captured: ReturnType<typeof captureWorktreePatch>;
  try {
    const base = result.worktree_manifest.source_commit ?? "HEAD";
    captured = captureWorktreePatch({
      worktree: result.worktree_manifest.path,
      base
    });
  } catch (err) {
    console.error("[orchestrator] patch capture failed:", err);
    return;
  }
  if (!captured) return;
  const attemptNumber =
    context.state.tasks[result.task_id]?.attempts.length ?? 1;
  const relativePath = `worker/${result.task_id}/attempt_${attemptNumber}_patch.diff`;
  const patchArtifact = writeArtifact(runRoot, relativePath, captured.patch, "text/x-diff");
  const evidence = (result.worker_result.evidence ?? {}) as Record<string, unknown>;
  evidence.patch_ref = patchArtifact.path;
  evidence.patch_sha256 = captured.sha256;
  evidence.patch_byte_length = captured.byteLength;
  if (result.worker_result.status !== "completed") evidence.patch_salvaged = true;
  if (captured.truncatedWarning) evidence.patch_truncated_warning = true;
  result.worker_result.evidence = evidence;
  // Re-persist worker_result so downstream consumers can read patch_ref from
  // disk. The original write happened in taskExecutor before patch capture
  // existed, so its sha256 in artifact_index would now mismatch the on-disk
  // bytes — refresh the index entry to keep stateReconciliation checks happy.
  const workerArtifact = writeArtifact(
    runRoot,
    `worker/${result.task_id}.json`,
    JSON.stringify(result.worker_result, null, 2)
  );
  context.mutateState((state) => {
    state.artifact_index = mergeArtifactIndex(state.artifact_index, [
      artifactIndexEntry({ artifact: patchArtifact, producer_phase: "provider", task_id: result.task_id }),
      artifactIndexEntry({ artifact: workerArtifact, producer_phase: "provider", task_id: result.task_id })
    ]);
  });
}

interface RunRepairAttemptInput {
  context: RunExecutionContext;
  run_id: string;
  paths: ReturnType<typeof runPaths>;
  workspace: string;
  worktree_root: string;
  task_id: string;
  prior_result: WaygentTaskExecutionResult;
  repair: { attempt_number: number; max_attempts: number };
  profile: ExecutionProfile;
  provider_processes: Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>>;
  task_file_claims: Array<{ path: string; mode: string }>;
}

type RunRepairAttemptOutcome =
  | { status: "dispatched"; worker_result: WorkerResult; patch_ref: string | null }
  | { status: "blocked"; reason: string };

async function runRepairAttempt(input: RunRepairAttemptInput): Promise<RunRepairAttemptOutcome> {
  const { context, run_id, paths, workspace, worktree_root, task_id, prior_result, repair, profile, provider_processes, task_file_claims } = input;
  const priorWorker = prior_result.worker_result;
  const patchRef = typeof priorWorker.evidence?.patch_ref === "string" ? priorWorker.evidence.patch_ref : null;
  if (!patchRef) {
    return { status: "blocked", reason: "missing_prior_patch_ref" };
  }
  const priorPatchAbs = join(paths.root, patchRef);
  const destination = join(worktree_root, `${task_id}_repair_${repair.attempt_number}`);
  const prep = prepareRepairWorktree({
    source_repo: workspace,
    destination,
    base_branch: "main",
    prior_patch_path: priorPatchAbs
  });
  if (prep.status === "blocked") {
    context.appendEvent((sequence) => buildRunEvent({
      run_id,
      sequence,
      event_type: "runway.repair_result",
      phase: "repair",
      outcome: "failed",
      summary: `Repair preparation blocked: ${prep.reason}`,
      payload: {
        task_id,
        attempt_number: repair.attempt_number,
        max_attempts: repair.max_attempts,
        status: "blocked",
        failure_class: prep.reason
      },
      trust_impact: "supports_failure"
    }));
    context.mutateState((state) => {
      state.repair_budget = {
        ...(state.repair_budget ?? {}),
        [task_id]: { max_attempts: repair.max_attempts, current: repair.attempt_number }
      };
    });
    context.flushState();
    return { status: "blocked", reason: prep.reason };
  }

  const verifications: RepairPacketVerificationInput[] = prior_result.verification_records.map((record) => {
    const ref = typeof record.kernel_result_ref === "string" ? record.kernel_result_ref : null;
    let stdout = "";
    let stderr = "";
    if (ref) {
      try {
        const kernelJson = JSON.parse(readFileSync(join(paths.root, ref), "utf8")) as { stdout?: unknown; stderr?: unknown };
        if (typeof kernelJson.stdout === "string") stdout = kernelJson.stdout;
        if (typeof kernelJson.stderr === "string") stderr = kernelJson.stderr;
      } catch {
        // leave excerpts empty if the kernel record cannot be read
      }
    }
    return {
      verification_id: String(record.verification_id ?? ""),
      command: String(record.command ?? ""),
      exit_code: typeof record.exit_code === "number" ? record.exit_code : null,
      timed_out: Boolean(record.timed_out),
      stdout,
      stderr,
      status: record.status === "passed" ? "passed" : "failed"
    };
  });

  const attemptId = `attempt_${task_id}_repair_${repair.attempt_number}`;
  const candidateId = `candidate_${task_id}_repair_${repair.attempt_number}`;
  const repairPacket = buildRepairPacket({
    task_id,
    attempt_id: attemptId,
    prior_worker_result: priorWorker,
    verifications
  });
  const packetArtifact = writeArtifact(
    paths.root,
    `task_packets/repair_${task_id}_${repair.attempt_number}.json`,
    `${JSON.stringify(repairPacket, null, 2)}\n`,
    "application/json"
  );
  const packetPath = join(paths.root, packetArtifact.path);

  context.appendEvent((sequence) => buildRunEvent({
    run_id,
    sequence,
    event_type: "runway.repair_dispatched",
    phase: "repair",
    outcome: "success",
    summary: "Repair worker dispatched.",
    payload: {
      task_id,
      attempt_id: attemptId,
      attempt_number: repair.attempt_number,
      max_attempts: repair.max_attempts,
      role: "repair",
      prior_diff_ref: repairPacket.prior_diff_ref,
      evidence_refs: [packetArtifact.path]
    },
    trust_impact: "neutral"
  }));

  const repairProcesses = applyRoleRoutingToProcesses(provider_processes, profile, "repair");
  const adapter: ProviderAdapter = profile.provider === "codex"
    ? new CodexProviderAdapter(repairProcesses.codex)
    : profile.provider === "claude"
      ? new ClaudeProviderAdapter(repairProcesses.claude)
      : new FakeProviderAdapter();

  const changedFilesHint = task_file_claims
    .filter((claim) => claim.mode !== "read_only")
    .map((claim) => claim.path);
  const prompt = [
    `Repair task: ${task_id}`,
    `task_packet_path: ${packetPath}`,
    "",
    "You are the Waygent repair worker. The worktree contains the prior diff already applied.",
    "Read the task packet for failed-verification evidence, and produce the smallest patch that",
    "makes the failed verifications pass."
  ].join("\n");

  const startedAt = new Date().toISOString();
  let adapterResult: ProviderAdapterRunResult | null = null;
  let adapterError: unknown = null;
  try {
    adapterResult = await adapter.run({
      task_id,
      candidate_id: candidateId,
      role: "fix",
      prompt,
      task_packet_path: packetPath,
      cwd: destination,
      ...(changedFilesHint.length > 0 ? { changed_files: changedFilesHint } : {})
    });
  } catch (err) {
    adapterError = err;
  }
  const completedAt = new Date().toISOString();

  let repairWorker: WorkerResult;
  let processEvidence: ProviderProcessEvidence | undefined;
  if (adapterResult) {
    repairWorker = adapterResult.worker;
    if (adapterResult.process) processEvidence = adapterResult.process;
  } else {
    repairWorker = {
      schema: "runway.worker_result.v1",
      task_id,
      candidate_id: candidateId,
      status: "blocked",
      changed_files: [],
      summary: adapterError instanceof Error ? adapterError.message : "Repair adapter crashed.",
      evidence: {},
      failure_class: "adapter_crashed"
    };
  }

  let cumulativePatchRef: string | null = null;
  let cumulativePatchSha: string | null = null;
  let cumulativePatchBytes: number | null = null;
  if (repairWorker.status === "completed") {
    try {
      const captured = captureWorktreePatch({ worktree: destination, base: "main" });
      if (captured) {
        const ref = `worker/${task_id}/attempt_${repair.attempt_number}_repair_patch.diff`;
        const patchArtifact = writeArtifact(paths.root, ref, captured.patch, "text/x-diff");
        cumulativePatchRef = patchArtifact.path;
        cumulativePatchSha = captured.sha256;
        cumulativePatchBytes = captured.byteLength;
        const ev = (repairWorker.evidence ?? {}) as Record<string, unknown>;
        ev.patch_ref = patchArtifact.path;
        ev.patch_sha256 = captured.sha256;
        ev.patch_byte_length = captured.byteLength;
        if (captured.truncatedWarning) ev.patch_truncated_warning = true;
        repairWorker.evidence = ev;
      }
    } catch (err) {
      console.error("[orchestrator] repair patch capture failed:", err);
    }
  }

  const workerArtifact = writeArtifact(
    paths.root,
    `worker/${task_id}/repair_${repair.attempt_number}.json`,
    JSON.stringify(repairWorker, null, 2)
  );
  const stdinArtifact = writeArtifact(paths.root, `provider/${attemptId}.stdin.txt`, prompt, "text/plain");
  const stdoutArtifact = writeArtifact(
    paths.root,
    `provider/${attemptId}.stdout.txt`,
    processEvidence?.stdout ?? JSON.stringify(repairWorker),
    "text/plain"
  );
  const stderrArtifact = writeArtifact(
    paths.root,
    `provider/${attemptId}.stderr.txt`,
    processEvidence?.stderr ?? "",
    "text/plain"
  );

  const providerAttempt: ProviderAttempt = {
    schema: "runway.provider_attempt.v1",
    attempt_id: attemptId,
    run_id,
    task_id,
    role: "fix",
    provider: profile.provider,
    command: profile.provider === "fake" ? ["fake-provider"] : [profile.provider],
    cwd: destination,
    stdin_ref: stdinArtifact.path,
    stdout_ref: stdoutArtifact.path,
    stderr_ref: stderrArtifact.path,
    event_stream_ref: null,
    exit_code: processEvidence?.exit_code ?? (repairWorker.status === "completed" ? 0 : 1),
    timed_out: processEvidence?.timed_out ?? false,
    started_at: processEvidence?.started_at ?? startedAt,
    completed_at: processEvidence?.completed_at ?? completedAt,
    worker_result_ref: workerArtifact.path,
    failure_class: repairWorker.failure_class ?? null,
    actual_model: adapterResult?.metadata?.actual_model ?? { model: null, reasoning: null, source: "unknown" },
    usage: adapterResult?.metadata?.usage ?? null,
    usage_source: adapterResult?.metadata?.usage_source ?? "unknown",
    ...(processEvidence ? { process: processEvidence } : {})
  };

  context.mutateState((state) => {
    state.provider_attempts = [...state.provider_attempts, providerAttempt];
    const indexEntries: ArtifactIndexEntry[] = [
      artifactIndexEntry({ artifact: packetArtifact, producer_phase: "task_packet", task_id }),
      artifactIndexEntry({ artifact: workerArtifact, producer_phase: "provider", task_id }),
      artifactIndexEntry({ artifact: stdinArtifact, producer_phase: "provider", task_id }),
      artifactIndexEntry({ artifact: stdoutArtifact, producer_phase: "provider", task_id }),
      artifactIndexEntry({ artifact: stderrArtifact, producer_phase: "provider", task_id })
    ];
    if (cumulativePatchRef && cumulativePatchSha !== null && cumulativePatchBytes !== null) {
      indexEntries.push(artifactIndexEntry({
        artifact: {
          path: cumulativePatchRef,
          sha256: cumulativePatchSha,
          byte_length: cumulativePatchBytes,
          media_type: "text/x-diff"
        },
        producer_phase: "provider",
        task_id
      }));
    }
    state.artifact_index = mergeArtifactIndex(state.artifact_index, indexEntries);
    const stateTask = state.tasks[task_id];
    if (stateTask) {
      stateTask.attempts = [...new Set([...stateTask.attempts, attemptId])];
    }
    state.repair_budget = {
      ...(state.repair_budget ?? {}),
      [task_id]: { max_attempts: repair.max_attempts, current: repair.attempt_number }
    };
    state.cost_ledger = recordProviderAttemptCost(state.cost_ledger ?? createEmptyCostLedger(), {
      task_id: providerAttempt.task_id,
      role: providerAttempt.role,
      usage: providerAttempt.usage ?? null,
      usage_source: providerAttempt.usage_source ?? "unknown",
      recorded_at: providerAttempt.completed_at ?? new Date().toISOString(),
      ...(providerAttempt.requested_model ? { requested_model: providerAttempt.requested_model } : {}),
      ...(providerAttempt.actual_model ? { actual_model: providerAttempt.actual_model } : {})
    });
  });

  context.appendEvent((sequence) => buildRunEvent({
    run_id,
    sequence,
    event_type: "runway.repair_result",
    phase: "repair",
    outcome: repairWorker.status === "completed" ? "success" : "failed",
    summary: repairWorker.summary,
    payload: {
      task_id,
      attempt_id: attemptId,
      attempt_number: repair.attempt_number,
      max_attempts: repair.max_attempts,
      status: repairWorker.status,
      patch_ref: cumulativePatchRef,
      summary: repairWorker.summary,
      failure_class: repairWorker.failure_class ?? null
    },
    trust_impact: repairWorker.status === "completed" ? "supports_success" : "supports_failure"
  }));

  return { status: "dispatched", worker_result: repairWorker, patch_ref: cumulativePatchRef };
}

function recordTaskRecovery(
  context: RunExecutionContext,
  input: { task_id: string; failure_class: FailureClass; prior_summary: string; evidence_refs: string[] }
): ReturnType<typeof appendSchedulerRecovery> {
  let recoveryRef: ReturnType<typeof appendSchedulerRecovery> | null = null;
  context.mutateState((state) => {
    state.current_phase = "recover";
    recoveryRef = appendSchedulerRecovery({ state, ...input });
  });
  const recovery = recoveryRef as ReturnType<typeof appendSchedulerRecovery> | null;
  if (!recovery) throw new Error(`recovery decision missing for ${input.task_id}`);
  const retryable = isRetryRecoveryAction(recovery.decision.action);
  context.appendEvent((sequence) => buildRunEvent({
    run_id: context.run_id,
    sequence,
    event_type: retryable ? "runway.recovery_scheduled" : "runway.recovery_decision_required",
    phase: "recover",
    outcome: retryable ? "success" : "blocked",
    summary: retryable
      ? "Scheduler recovery retry scheduled."
      : "Scheduler recovery requires an operator decision.",
    payload: {
      task_id: input.task_id,
      failure_class: input.failure_class,
      action: recovery.decision.action,
      attempt_number: recovery.decision.attempt_number,
      max_attempts: recovery.decision.max_attempts,
      evidence_refs: input.evidence_refs
    },
    trust_impact: retryable ? "neutral" : "requires_review"
  }));
  return recovery;
}

function isRetryRecoveryAction(action: string): boolean {
  return action === "retry_with_strict_prompt" || action === "retry_with_evidence";
}

function markStateTaskReadyForRetry(
  context: RunExecutionContext,
  taskId: string,
  failureClass: FailureClass
): void {
  context.mutateState((state) => {
    const task = state.tasks[taskId];
    if (!task) return;
    task.status = "ready";
    task.latest_failure_class = failureClass;
  });
}

function taskRecoveryEvidenceRefs(result: WaygentTaskExecutionResult): string[] {
  const refs = [
    result.provider_attempt.worker_result_ref,
    ...result.verification_records
      .map((record) => record.kernel_result_ref)
      .filter((ref): ref is string => typeof ref === "string" && ref.length > 0),
    result.task_packet_path
  ].filter((ref): ref is string => typeof ref === "string" && ref.length > 0);
  return [...new Set(refs)];
}

function errorSummary(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function pauseRunForBudget(context: RunExecutionContext, activeTaskIds: string[]): void {
  context.mutateState((state) => {
    state.status = "blocked";
    state.lifecycle_outcome = "blocked";
    state.current_phase = "dispatch";
    state.apply = { status: "blocked", reason: "budget_paused" };
    for (const taskId of activeTaskIds) {
      const task = state.tasks[taskId];
      if (task && task.status !== "verified" && task.status !== "applied") {
        task.status = "blocked";
        task.latest_failure_class = "needs_infra_fix";
      }
    }
    state.recovery = [...state.recovery, {
      failure_class: "budget_paused",
      reason: "budget_paused",
      budget_cap_usd: state.budget_cap_usd,
      cost_usd: state.cost_ledger?.totals.cost_usd ?? 0,
      recorded_at: new Date().toISOString()
    }];
  });
  context.appendEvent((sequence) => buildRunEvent({
    run_id: context.run_id,
    sequence,
    event_type: "platform.cost_budget_paused",
    phase: "cost",
    outcome: "blocked",
    summary: "Budget cap paused execution at a safe boundary.",
    payload: { budget_cap_usd: context.state.budget_cap_usd, cost_ledger: context.state.cost_ledger },
    trust_impact: "requires_review"
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

function combinedApplyArtifactEntries(combined: CombinedCheckpointPatchResult | undefined): ArtifactIndexEntry[] {
  if (!combined) return [];
  return [
    combined.patch_artifact
      ? artifactIndexEntry({ artifact: combined.patch_artifact, producer_phase: "combined_apply", task_id: null })
      : null,
    artifactIndexEntry({ artifact: combined.evidence_artifact, producer_phase: "combined_apply", task_id: null })
  ].filter((entry): entry is ArtifactIndexEntry => entry !== null);
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

function requestedModelForProfile(profile: ExecutionProfile, role: WorkerRoleSlot = "implement") {
  if (profile.execution_mode === "single-agent") {
    return {
      model: profile.main.model ?? null,
      reasoning: profile.main.reasoning ?? null
    };
  }
  const source = roleProfileFor(profile, role);
  return {
    model: source.model ?? null,
    reasoning: source.reasoning ?? null
  };
}

export function applyRoleRoutingToProcesses(
  processes: Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>>,
  profile: ExecutionProfile,
  role: WorkerRoleSlot
): Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>> {
  if (profile.execution_mode === "single-agent") return processes;
  const target = roleProfileFor(profile, role);
  const next: typeof processes = { ...processes };
  if (next.codex) {
    next.codex = { ...next.codex, model: target.model, effort: target.reasoning };
  }
  if (next.claude) {
    next.claude = { ...next.claude, model: target.model, effort: target.reasoning };
  }
  return next;
}

export function applyCodexResumeContext(
  processes: Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>>,
  resumeSessionId: string | undefined
): Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>> {
  if (!resumeSessionId || !processes.codex) return processes;
  if (processes.codex.resume_session_id) return processes;
  return {
    ...processes,
    codex: { ...processes.codex, resume_session_id: resumeSessionId }
  };
}

function extractSessionIdFromWorker(worker: { evidence: Record<string, unknown> } | undefined): string | null {
  if (!worker) return null;
  const evidence = worker.evidence ?? {};
  const value = (evidence as Record<string, unknown>).session_id;
  return typeof value === "string" && value.length > 0 ? value : null;
}

function planNormalizationPayload(
  normalizedPlan: ReturnType<typeof normalizeWaygentPlanInput>,
  artifactRef: string | null
): Record<string, unknown> {
  return {
    mode: normalizedPlan.mode,
    source_path: normalizedPlan.path,
    task_count: normalizedPlan.task_count,
    diagnostics: normalizedPlan.diagnostics,
    normalized_plan_ref: artifactRef
  };
}

export function resolveProviderProcesses(
  profile: ExecutionProfile,
  overrides: Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>> | undefined
): Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>> {
  const result: Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>> = {};
  if (profile.provider === "codex") {
    const userCodex = overrides?.codex;
    result.codex = {
      executable: userCodex?.executable ?? "codex",
      args: userCodex?.args ?? ["exec", "--json", "-"],
      ...(userCodex?.cwd ? { cwd: userCodex.cwd } : {}),
      ...(userCodex?.env ? { env: userCodex.env } : {}),
      ...(userCodex?.timeout_ms ? { timeout_ms: userCodex.timeout_ms } : {}),
      ...(userCodex?.resume_session_id ? { resume_session_id: userCodex.resume_session_id } : {}),
      model: userCodex?.model ?? profile.subagent.model,
      effort: userCodex?.effort ?? profile.subagent.reasoning
    };
  } else if (overrides?.codex) {
    result.codex = overrides.codex;
  }
  if (profile.provider === "claude") {
    const userClaude = overrides?.claude;
    result.claude = {
      executable: userClaude?.executable ?? "claude",
      args: userClaude?.args ?? ["-p", "--output-format", "stream-json", "--include-partial-messages", "--verbose"],
      ...(userClaude?.cwd ? { cwd: userClaude.cwd } : {}),
      ...(userClaude?.env ? { env: userClaude.env } : {}),
      ...(userClaude?.timeout_ms ? { timeout_ms: userClaude.timeout_ms } : {}),
      ...(userClaude?.timeout_ms_by_role ? { timeout_ms_by_role: userClaude.timeout_ms_by_role } : {}),
      ...(userClaude?.settings_path ? { settings_path: userClaude.settings_path } : {}),
      ...(userClaude?.mcp_config_path ? { mcp_config_path: userClaude.mcp_config_path } : {}),
      ...(userClaude?.session_id ? { session_id: userClaude.session_id } : {}),
      ...(userClaude?.resume_session_id ? { resume_session_id: userClaude.resume_session_id } : {}),
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
  switch (process.platform) {
    case "darwin":
      return join(homedir(), "Library", "Application Support", "waygent", "runs");
    case "linux": {
      const xdg = process.env.XDG_DATA_HOME;
      return xdg && xdg.length > 0
        ? join(xdg, "waygent", "runs")
        : join(homedir(), ".local", "share", "waygent", "runs");
    }
    case "win32":
      return join(
        process.env.LOCALAPPDATA ?? join(homedir(), "AppData", "Local"),
        "waygent",
        "runs"
      );
    default:
      process.stderr.write(
        `WARN: unsupported platform '${process.platform}'; using tmpdir for waygent runs (volatile)\n`
      );
      return join(tmpdir(), "waygent-runs");
  }
}

function budgetPolicyFromState(state: WaygentRunStateV2): BudgetPolicy {
  const policy: BudgetPolicy = {};
  if (state.budget_cap_usd !== undefined) policy.budget_cap_usd = state.budget_cap_usd;
  if (state.budget_action !== undefined) policy.budget_action = state.budget_action;
  return policy;
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
  const checkpointRefs: string[] = [];
  const visited = new Set<string>();
  const visit = (taskId: string) => {
    if (visited.has(taskId)) return;
    visited.add(taskId);
    const task = state.tasks[taskId];
    if (!task) return;
    for (const dependency of task.dependencies) visit(dependency);
    checkpointRefs.push(...task.checkpoint_refs);
  };
  for (const dependency of dependencies) visit(dependency);
  return [...new Set(checkpointRefs)];
}
