import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname } from "node:path";
import { join } from "node:path";
import type { AgentLensEvent, ProviderAttempt, ProviderProcessEvidence, WaygentRunStateV2, WorkerResult } from "@waygent/contracts";
import { buildTaskPacket } from "@waygent/context-packer";
import { planWorktree } from "@waygent/kernel-client";
import { projectFailureSummary, projectTimeline, projectTrustReport } from "@waygent/lens-projectors";
import { appendEvent, readEvents, rebuildRunSummary, runPaths, writeArtifact, writeLatestRunId } from "@waygent/lens-store";
import { ClaudeProviderAdapter, CodexProviderAdapter, FakeProviderAdapter, type ProviderAdapter, type ProviderProcessOptions } from "@waygent/provider-adapters";
import { buildDurableProjection, mergeCandidate } from "@waygent/runway-control";
import { createCheckpointArtifact, createCombinedCheckpointPatchArtifact, dryRunCheckpointPatch } from "./checkpointArtifacts";
import { buildCompletionAudit } from "./completionAudit";
import { resolveExecutionProfile, type ProfileOverride, type ProviderName } from "./executionProfile";
import { resolvePlanInput } from "./planDiscovery";
import { parseWaygentPlan, type ParsedWaygentTask } from "./planParser";
import { buildRunEvent } from "./runEvents";
import { readRunStateV2, writeRunStateV2 } from "./runState";
import { classifySourceCheckout } from "./sourceCheckout";
import { reconcileRunState } from "./stateReconciliation";
import { buildTaskGraphFromPlan } from "./taskGraph";
import { runVerificationCommands } from "./verification";

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
  writeRunStateV2(options.root, initialState);

  const started = buildRunEvent({
    run_id: runId,
    sequence: 1,
    event_type: "platform.run_started",
    phase: "platform",
    outcome: "running",
    summary: "Run opened.",
    payload: { plan: planInput.path ?? options.plan, spec: options.spec, profile: providerProfile }
  });
  appendEvent(paths.events, started);
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: 2,
    event_type: "runway.plan_loaded",
    phase: "plan",
    outcome: "success",
    summary: "Plan parsed into task graph.",
    payload: { task_count: parsed.tasks.length, profile: providerProfile, worktree: plannedWorktree }
  }));
  const preflightEvent = buildRunEvent({
    run_id: runId,
    sequence: 3,
    event_type: "runway.preflight_result",
    phase: "preflight",
    outcome: preflight.status === "dirty_related" ? "blocked" : "success",
    summary: preflight.status === "clean"
      ? "Source checkout preflight passed."
      : preflight.status === "dirty_unrelated"
        ? "Source checkout preflight found unrelated dirty files and continued."
        : "Source checkout preflight blocked dispatch.",
    payload: preflight,
    trust_impact: preflight.status === "clean" ? "supports_success" : "neutral"
  });
  appendEvent(paths.events, preflight.status === "dirty_unrelated" ? { ...preflightEvent, severity: "warning" } : preflightEvent);

  if (preflight.status === "dirty_related") {
    updateRunStateV2(options.root, runId, (state) => {
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
    return finalizeRun(options.root, paths, runId, projection, 4);
  }

  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: 4,
    event_type: "runway.safe_wave_selected",
    phase: "schedule",
    outcome: "success",
    summary: "Safe wave selected.",
    payload: { safe_wave: projection.safe_wave }
  }));

  const verificationCommands = new Map<string, string[]>();
  const providerAttempts: ProviderAttempt[] = [];
  const verificationRecords: Array<Record<string, unknown>> = [];
  const provider = createProviderAdapter(profile.provider, options.provider_processes);
  let sequence = 5;

  async function runOneTask(taskId: string): Promise<void> {
    const task = graph.tasks.get(taskId);
    if (!task) throw new Error(`task ${taskId} missing from graph`);
    const parsedTask = parsed.tasks.find((candidate) => candidate.id === task.id);
    if (!parsedTask) throw new Error(`task ${task.id} missing from parsed plan`);
    const taskWorktree = planWorktree({ run_id: runId, task_id: task.id, workspace, worktree_root: worktreeRoot });
    prepareTaskWorktree(workspace, taskWorktree.path);
    verificationCommands.set(task.id, parsedTask.verification_commands.length > 0 ? parsedTask.verification_commands : ["printf hello"]);
    const packet = buildTaskPacket({
      run_id: runId,
      task: parsedTask,
      role: "implement",
      plan_excerpt: parsedTask.title,
      spec_excerpt: options.spec ?? "",
      previous_failures: []
    });
    const packetArtifact = writeArtifact(paths.root, `task_packets/${task.id}.json`, `${JSON.stringify(packet, null, 2)}\n`);
    const packetPath = join(paths.root, packetArtifact.path);
    updateRunStateV2(options.root, runId, (state) => {
      const stateTask = state.tasks[task.id];
      if (stateTask) {
        stateTask.status = "running";
        stateTask.task_packet_path = packetPath;
        stateTask.task_packet_sha256 = packetArtifact.sha256;
        stateTask.timing.started = new Date().toISOString();
      }
      state.current_phase = "dispatch";
    });
    const prompt = buildTaskPrompt(parsedTask, packetPath);
    const attemptId = `attempt_${task.id}_1`;
    const attemptStarted = new Date().toISOString();
    const stdinArtifact = writeArtifact(paths.root, `provider/${attemptId}.stdin.txt`, prompt, "text/plain");
    const adapterResult = await provider.run({
      task_id: task.id,
      candidate_id: `candidate_${task.id}`,
      role: "implement",
      prompt,
      task_packet_path: packetPath,
      cwd: taskWorktree.path,
      changed_files: parsedTask.file_claims.filter((claim) => claim.mode !== "read_only").map((claim) => claim.path)
    });
    const { worker, processEvidence } = normalizeProviderRunResult(adapterResult);
    const workerArtifact = writeArtifact(paths.root, `worker/${task.id}.json`, JSON.stringify(worker, null, 2));
    const stdoutArtifact = writeArtifact(paths.root, `provider/${attemptId}.stdout.txt`, processEvidence?.stdout ?? JSON.stringify(worker), "text/plain");
    const stderrArtifact = writeArtifact(paths.root, `provider/${attemptId}.stderr.txt`, processEvidence?.stderr ?? "", "text/plain");
    const attempt: ProviderAttempt = {
      schema: "runway.provider_attempt.v1",
      attempt_id: attemptId,
      run_id: runId,
      task_id: task.id,
      role: "implement",
      provider: profile.provider,
      command: profile.provider === "fake" ? ["fake-provider"] : [profile.provider],
      cwd: taskWorktree.path,
      stdin_ref: stdinArtifact.path,
      stdout_ref: stdoutArtifact.path,
      stderr_ref: stderrArtifact.path,
      event_stream_ref: null,
      exit_code: processEvidence?.exit_code ?? (worker.status === "completed" ? 0 : 1),
      timed_out: processEvidence?.timed_out ?? false,
      started_at: processEvidence?.started_at ?? attemptStarted,
      completed_at: processEvidence?.completed_at ?? new Date().toISOString(),
      worker_result_ref: workerArtifact.path,
      failure_class: worker.failure_class ?? null,
      ...(processEvidence ? { process: processEvidence } : {})
    };
    providerAttempts.push(attempt);
    updateRunStateV2(options.root, runId, (state) => {
      state.provider_attempts = [...providerAttempts];
      state.tasks[task.id]?.attempts.push(attemptId);
    });
    appendEvent(paths.events, buildRunEvent({
      run_id: runId,
      sequence: sequence++,
      event_type: "runway.worker_result",
      phase: "worker",
      outcome: worker.status === "completed" ? "success" : "failed",
      summary: worker.summary,
      payload: { worker, attempt }
    }));
    if (profile.provider === "fake") materializeFakeProviderResult(taskWorktree.path, parsedTask);
    const verification = await runVerificationCommands({
      run_id: runId,
      task_id: task.id,
      cwd: taskWorktree.path,
      commands: verificationCommands.get(task.id) ?? ["printf hello"]
    });
    const taskVerificationRecords = verification.results.map((kernel, index) => {
      const command = verificationCommands.get(task.id)?.[index] ?? "";
      const kernelArtifact = writeArtifact(paths.root, `kernel/${kernel.request_id}.json`, JSON.stringify(kernel, null, 2));
      return {
        verification_id: kernel.request_id,
        task_id: task.id,
        command,
        cwd: taskWorktree.path,
        kernel_result_ref: kernelArtifact.path,
        exit_code: kernel.exit_code,
        timed_out: kernel.timed_out,
        stdout_sha256: kernel.stdout_sha256,
        stderr_sha256: kernel.stderr_sha256,
        status: kernel.exit_code === 0 && !kernel.timed_out ? "passed" : "failed"
      };
    });
    verificationRecords.push(...taskVerificationRecords);
    const verificationPassed = verification.status === "passed" && worker.status === "completed";
    appendEvent(paths.events, buildRunEvent({
      run_id: runId,
      sequence: sequence++,
      event_type: "runway.verification_result",
      phase: "verify",
      outcome: verificationPassed ? "success" : "failed",
      summary: verificationPassed ? "Verification passed with kernel evidence." : "Verification failed with kernel evidence.",
      payload: { worker, verification: taskVerificationRecords, checkpoint_ref: null }
    }));
    if (verificationPassed) {
      const verified = mergeCandidate({ task_id: task.id, candidate_id: worker.candidate_id, reviewed: true, verified: true });
      const hasWritableClaims = parsedTask.file_claims.some((claim) => claim.mode !== "read_only");
      if (verified.merged && hasWritableClaims) {
        const checkpoint = createCheckpointArtifact({
          run_root: paths.root,
          run_id: runId,
          task_id: task.id,
          candidate_id: worker.candidate_id,
          worktree_path: taskWorktree.path,
          changed_files: worker.changed_files,
          verification_refs: taskVerificationRecords.map((record) => String(record.kernel_result_ref))
        });
        const dryRun = dryRunCheckpointPatch({
          run_root: paths.root,
          checkpoint_ref: checkpoint.manifest_ref,
          source: workspace
        });
        appendEvent(paths.events, buildRunEvent({
          run_id: runId,
          sequence: sequence++,
          event_type: "runway.checkpoint_created",
          phase: "checkpoint",
          outcome: "success",
          summary: "Verified checkpoint artifact created.",
          payload: {
            task_id: task.id,
            candidate_id: worker.candidate_id,
            checkpoint_ref: checkpoint.manifest_ref,
            patch_ref: checkpoint.patch_ref
          }
        }));
        appendEvent(paths.events, buildRunEvent({
          run_id: runId,
          sequence: sequence++,
          event_type: "runway.apply_dry_run_result",
          phase: "checkpoint",
          outcome: dryRun.status === "passed" ? "success" : "blocked",
          summary: dryRun.status === "passed" ? "Checkpoint patch dry-run passed." : "Checkpoint patch dry-run failed.",
          payload: { task_id: task.id, checkpoint_ref: checkpoint.manifest_ref, dry_run: dryRun }
        }));
        if (dryRun.status === "passed") {
          task.checkpoint_ref = checkpoint.manifest_ref;
        } else {
          task.latest_failure_class = "missing_checkpoint";
        }
      } else {
        task.latest_failure_class = "missing_checkpoint";
      }
    }
    updateRunStateV2(options.root, runId, (state) => {
      state.current_phase = "verify";
      state.verification = [...verificationRecords];
      const stateTask = state.tasks[task.id];
      if (stateTask) {
        stateTask.status = verificationPassed ? "verified" : "blocked";
        stateTask.latest_failure_class = verificationPassed ? task.latest_failure_class ?? null : worker.failure_class ?? "verification_failed";
        stateTask.checkpoint_refs = task.checkpoint_ref ? [task.checkpoint_ref] : [];
        stateTask.timing.completed = new Date().toISOString();
      }
    });
    if (verificationPassed && task.checkpoint_ref) {
      task.status = "APPLIED";
    } else {
      task.status = "FAILED_TERMINAL";
      task.latest_failure_class = task.latest_failure_class ?? worker.failure_class ?? "verification_failed";
    }
  }

  let activeSafeWave = safeWave;
  let waveIndex = 1;
  while (activeSafeWave.length > 0) {
    for (const taskId of activeSafeWave) {
      await runOneTask(taskId);
    }
    waveIndex += 1;
    const nextProjection = buildDurableProjection(graph);
    activeSafeWave = nextProjection.safe_wave;
    if (activeSafeWave.length === 0) break;
    appendEvent(paths.events, buildRunEvent({
      run_id: runId,
      sequence: sequence++,
      event_type: "runway.safe_wave_selected",
      phase: "schedule",
      outcome: "success",
      summary: "Safe wave selected.",
      payload: { safe_wave: activeSafeWave, wave_id: `wave_${waveIndex}` }
    }));
    updateRunStateV2(options.root, runId, (state) => {
      state.safe_waves.push({ wave_id: `wave_${waveIndex}`, ready: activeSafeWave, withheld: nextProjection.withheld_tasks });
      for (const taskId of activeSafeWave) {
        const stateTask = state.tasks[taskId];
        if (stateTask) stateTask.status = "ready";
      }
    });
  }

  let completionAuditStatus = "failed";
  updateRunStateV2(options.root, runId, (state) => {
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
      required_checks: parsed.tasks.flatMap((task) => verificationCommands.get(task.id) ?? task.verification_commands),
      verification_evidence: verificationRecords,
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
  const reconciliation = reconcileRunState(options.root, runId);
  updateRunStateV2(options.root, runId, (state) => {
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
  return finalizeRun(options.root, paths, runId, projection, sequence);
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
  const trust = projectTrustReport(readEvents(paths.events));
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "lens.trust_report_updated",
    phase: "lens",
    outcome: "success",
    summary: "Trust report updated.",
    payload: { trust_status: trust.trust_status }
  }));
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

function normalizeProviderRunResult(
  result: WorkerResult | { worker: WorkerResult; process?: ProviderProcessEvidence }
): { worker: WorkerResult; processEvidence?: ProviderProcessEvidence } {
  if (typeof result === "object" && result !== null && "worker" in result) {
    return {
      worker: result.worker,
      ...(result.process ? { processEvidence: result.process } : {})
    };
  }
  return { worker: result };
}

function createProviderAdapter(
  provider: ProviderName,
  processes: RunWaygentOptions["provider_processes"] = {}
): ProviderAdapter {
  if (provider === "codex") return new CodexProviderAdapter(processes.codex);
  if (provider === "claude") return new ClaudeProviderAdapter(processes.claude);
  return new FakeProviderAdapter();
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

function buildTaskPrompt(task: { title: string; verification_commands: string[] } | undefined, taskPacketPath?: string): string {
  if (!task) return "Waygent task";
  return [
    task.title,
    taskPacketPath ? `task_packet_path: ${taskPacketPath}` : null,
    "Verify:",
    task.verification_commands.join("\n")
  ].filter(Boolean).join("\n\n");
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

function materializeFakeProviderResult(worktree: string, task: ParsedWaygentTask): void {
  for (const claim of task.file_claims.filter((item) => item.mode !== "read_only")) {
    const target = join(worktree, claim.path);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, `Waygent fake provider output for ${task.id}\n`);
  }
}

function prepareTaskWorktree(source: string, target: string): void {
  rmSync(target, { recursive: true, force: true });
  mkdirSync(dirname(target), { recursive: true });
  if (!isGitWorktree(source)) {
    mkdirSync(target, { recursive: true });
    cpSync(source, target, { recursive: true, force: true });
    initGitSnapshot(target);
    return;
  }
  const clone = spawnSync("git", ["clone", "--quiet", "--shared", source, target], {
    cwd: source,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (clone.status !== 0) {
    throw new Error(`failed to create task worktree at ${target}: ${clone.stderr}`);
  }
  spawnSync("git", ["checkout", "--detach", "HEAD"], {
    cwd: target,
    encoding: "utf8",
    stdio: ["ignore", "ignore", "ignore"]
  });
  const reset = spawnSync("git", ["reset", "--hard", "HEAD"], {
    cwd: target,
    encoding: "utf8",
    stdio: ["ignore", "ignore", "pipe"]
  });
  if (reset.status !== 0) {
    throw new Error(`failed to prepare task worktree at ${target}: ${reset.stderr}`);
  }
}

function isGitWorktree(source: string): boolean {
  const result = spawnSync("git", ["rev-parse", "--is-inside-work-tree"], {
    cwd: source,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"]
  });
  return result.status === 0 && result.stdout.trim() === "true";
}

function initGitSnapshot(target: string): void {
  spawnSync("git", ["init", "-q"], { cwd: target });
  spawnSync("git", ["config", "user.email", "test@example.com"], { cwd: target });
  spawnSync("git", ["config", "user.name", "Waygent"], { cwd: target });
  spawnSync("git", ["add", "-A"], { cwd: target });
  spawnSync("git", ["commit", "--allow-empty", "-q", "-m", "waygent base"], { cwd: target });
}

function updateRunStateV2(root: string, runId: string, mutate: (state: WaygentRunStateV2) => void): void {
  const state = readRunStateV2(root, runId);
  mutate(state);
  state.timestamps.updated_at = new Date().toISOString();
  writeRunStateV2(root, state);
}
