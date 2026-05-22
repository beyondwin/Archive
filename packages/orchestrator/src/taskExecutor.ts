import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import type {
  ArtifactIndexEntry,
  ExecutionPhaseTiming,
  FailureClass,
  ProviderAttempt,
  ProviderProcessEvidence,
  ModelRequest,
  WaygentWorktreeManifest,
  WorkerResult
} from "@waygent/contracts";
import { buildTaskPacket } from "@waygent/context-packer";
import { sha256, writeArtifact } from "@waygent/lens-store";
import {
  ClaudeProviderAdapter,
  CodexProviderAdapter,
  FakeProviderAdapter,
  type ProviderAdapter,
  type ProviderAdapterRunResult,
  type ProviderProcessOptions,
  type ProviderRunMetadata
} from "@waygent/provider-adapters";
import { mergeCandidate } from "@waygent/runway-control";
import { artifactIndexEntry } from "./artifactIndex";
import { createCheckpointArtifact, dryRunCheckpointPatch, resolveCheckpointPatch } from "./checkpointArtifacts";
import { listActualChangedFiles, validateDiffScope } from "./diffScope";
import type { ProviderName } from "./executionProfile";
import type { ParsedWaygentTask } from "./planParser";
import type { RunEventInput } from "./runEvents";
import { prepareVerificationEnvironment, type VerificationEnvironmentEvidence } from "./verificationEnvironment";
import { debugArtifactDenials, evaluateFinalOutputHooks, evaluatePreDispatchHooks, type HookDenial } from "./runtimeHooks";
import { runVerificationCommands, type VerificationRunOutput } from "./verification";
import { prepareManagedTaskWorktree } from "./worktreeManager";

export type TaskExecutionEventIntent = Omit<RunEventInput, "sequence">;

export interface WaygentTaskExecutionResult {
  task_id: string;
  status: "verified" | "blocked";
  latest_failure_class: FailureClass | null;
  worktree_manifest: WaygentWorktreeManifest;
  task_packet_path: string;
  task_packet_sha256: string;
  provider_attempt: ProviderAttempt;
  verification_records: Array<Record<string, unknown>>;
  checkpoint_refs: string[];
  artifact_index_entries: ArtifactIndexEntry[];
  events: TaskExecutionEventIntent[];
  timing: { started: string; completed: string; duration_ms: number };
  phase_timings: ExecutionPhaseTiming[];
  worker_result: WorkerResult;
}

export interface ExecuteWaygentTaskInput {
  root: string;
  run_id: string;
  workspace: string;
  worktree_root: string;
  task: ParsedWaygentTask;
  checkpoint_inputs: string[];
  spec: string | null;
  provider: ProviderName;
  provider_processes?: Partial<Record<Exclude<ProviderName, "fake">, ProviderProcessOptions>>;
  decisions?: Array<{ decision_id: string; summary: string }>;
  requested_model?: ModelRequest;
  hooks_enabled?: boolean;
}

export async function executeWaygentTask(input: ExecuteWaygentTaskInput): Promise<WaygentTaskExecutionResult> {
  const startedAtMs = performance.now();
  const started = new Date().toISOString();
  const managedWorktree = prepareManagedTaskWorktree({
    run_id: input.run_id,
    task_id: input.task.id,
    workspace: input.workspace,
    worktree_root: input.worktree_root
  });
  const worktreeManifest = managedWorktree.manifest;
  const taskWorktree = {
    path: worktreeManifest.path,
    branch: worktreeManifest.branch,
    source: worktreeManifest.source
  };
  const phaseTimings: ExecutionPhaseTiming[] = [managedWorktree.timing];
  const artifactIndexEntries: ArtifactIndexEntry[] = [];

  materializeCheckpointInputs({
    run_root: inputRunRoot(input),
    worktree: taskWorktree.path,
    checkpoint_refs: input.checkpoint_inputs
  });

  const commands = input.task.verification_commands.length > 0 ? input.task.verification_commands : ["printf hello"];
  const packet = buildTaskPacket({
    run_id: input.run_id,
    task: input.task,
    role: "implement",
    plan_excerpt: taskPlanExcerpt(input.task),
    spec_excerpt: input.spec ?? "",
    checkpoint_inputs: input.checkpoint_inputs,
    previous_failures: [],
    decisions: input.decisions ?? [],
    workspace: input.workspace
  });
  const packetArtifact = writeArtifact(inputRunRoot(input), `task_packets/${input.task.id}.json`, `${JSON.stringify(packet, null, 2)}\n`);
  artifactIndexEntries.push(artifactIndexEntry({ artifact: packetArtifact, producer_phase: "task_packet", task_id: input.task.id }));
  const packetPath = join(inputRunRoot(input), packetArtifact.path);
  const prompt = buildTaskPrompt(input.task, packetPath);
  const attemptId = `attempt_${input.task.id}_1`;
  const attemptStarted = new Date().toISOString();
  const stdinArtifact = writeArtifact(inputRunRoot(input), `provider/${attemptId}.stdin.txt`, prompt, "text/plain");
  artifactIndexEntries.push(artifactIndexEntry({ artifact: stdinArtifact, producer_phase: "provider", task_id: input.task.id }));
  const preHook = evaluatePreDispatchHooks({
    enabled: input.hooks_enabled ?? true,
    task_id: input.task.id,
    commands,
    file_claims: input.task.file_claims
  });
  if (preHook.status === "denied") {
    return hookDeniedResult({
      input,
      started,
      startedAtMs,
      worktreeManifest,
      packetPath,
      packetSha256: packetArtifact.sha256,
      phaseTimings,
      artifactIndexEntries,
      stdinRef: stdinArtifact.path,
      attemptId,
      attemptStarted,
      denials: preHook.denials
    });
  }
  const provider = createProviderAdapter(input.provider, input.provider_processes);
  const { value: adapterResult, timing: providerTiming } = await measurePhase("provider", () => provider.run({
    task_id: input.task.id,
    candidate_id: `candidate_${input.task.id}`,
    role: "implement",
    prompt,
    task_packet_path: packetPath,
    cwd: taskWorktree.path,
    changed_files: writableClaimPaths(input.task)
  }));
  phaseTimings.push(providerTiming);
  const { worker, processEvidence, metadata } = normalizeProviderRunResult(adapterResult);
  const finalHook = evaluateFinalOutputHooks({
    enabled: input.hooks_enabled ?? true,
    task_id: input.task.id,
    worker,
    stdout: processEvidence?.stdout ?? "",
    stderr: processEvidence?.stderr ?? ""
  });
  if (finalHook.status === "denied" && worker.status === "completed") {
    worker.status = "blocked";
    worker.failure_class = "permission_denied";
    worker.summary = "Runtime hook denied provider output.";
    worker.evidence = { ...worker.evidence, hook_denials: finalHook.denials };
  }
  const workerArtifact = writeArtifact(inputRunRoot(input), `worker/${input.task.id}.json`, JSON.stringify(worker, null, 2));
  const stdoutArtifact = writeArtifact(inputRunRoot(input), `provider/${attemptId}.stdout.txt`, processEvidence?.stdout ?? JSON.stringify(worker), "text/plain");
  const stderrArtifact = writeArtifact(inputRunRoot(input), `provider/${attemptId}.stderr.txt`, processEvidence?.stderr ?? "", "text/plain");
  artifactIndexEntries.push(
    artifactIndexEntry({ artifact: workerArtifact, producer_phase: "provider", task_id: input.task.id }),
    artifactIndexEntry({ artifact: stdoutArtifact, producer_phase: "provider", task_id: input.task.id }),
    artifactIndexEntry({ artifact: stderrArtifact, producer_phase: "provider", task_id: input.task.id })
  );
  const attempt: ProviderAttempt = {
    schema: "runway.provider_attempt.v1",
    attempt_id: attemptId,
    run_id: input.run_id,
    task_id: input.task.id,
    role: "implement",
    provider: input.provider,
    command: input.provider === "fake" ? ["fake-provider"] : [input.provider],
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
    ...(input.requested_model ? { requested_model: input.requested_model } : {}),
    actual_model: metadata?.actual_model ?? { model: null, reasoning: null, source: "unknown" },
    usage: metadata?.usage ?? null,
    usage_source: metadata?.usage_source ?? "unknown",
    ...(processEvidence ? { process: processEvidence } : {})
  };
  const workerEvent: TaskExecutionEventIntent = {
    run_id: input.run_id,
    event_type: "runway.worker_result",
    phase: "worker",
    outcome: worker.status === "completed" ? "success" : "failed",
    summary: worker.summary,
    payload: { task_id: input.task.id, failure_class: worker.failure_class ?? null, worker, attempt }
  };
  const events: TaskExecutionEventIntent[] = [workerEvent];
  if (preHook.status === "bypassed") {
    events.push({
      run_id: input.run_id,
      event_type: "kernel.hook_bypassed",
      phase: "hook",
      outcome: "success",
      summary: "Runtime hooks bypassed by configuration.",
      payload: { task_id: input.task.id },
      trust_impact: "neutral"
    });
  }
  for (const denial of finalHook.denials) {
    events.push({
      run_id: input.run_id,
      event_type: "kernel.hook_denied",
      phase: "hook",
      outcome: "blocked",
      summary: denial.reason,
      payload: { task_id: input.task.id, denial },
      trust_impact: "requires_review"
    });
  }
  if (attempt.actual_model?.model && input.requested_model?.model && attempt.actual_model.model !== input.requested_model.model) {
    events.push({
      run_id: input.run_id,
      event_type: "lens.model_attestation_mismatch",
      phase: "lens",
      outcome: "blocked",
      summary: "Provider actual model differed from requested model.",
      payload: { task_id: input.task.id, requested_model: input.requested_model, actual_model: attempt.actual_model },
      trust_impact: "requires_review"
    });
  } else if (attempt.actual_model?.model) {
    events.push({
      run_id: input.run_id,
      event_type: "lens.model_attestation_confirmed",
      phase: "lens",
      outcome: "success",
      summary: "Provider model attestation recorded.",
      payload: { task_id: input.task.id, requested_model: input.requested_model ?? null, actual_model: attempt.actual_model },
      trust_impact: "neutral"
    });
  }

  if (input.provider === "fake") materializeFakeProviderResult(taskWorktree.path, input.task);

  let verificationEnvironmentEvidence: VerificationEnvironmentEvidence = {
    status: "skipped",
    strategy: "none",
    created_paths: [],
    cleanup_status: "not_needed",
    reason: "not_prepared"
  };
  const { value: verification, timing: verificationTiming } = await measurePhase("verification", async () => {
    const verificationEnvironment = prepareVerificationEnvironment({
      workspace: input.workspace,
      worktree: taskWorktree.path,
      disabled: process.env.WAYGENT_DISABLE_VERIFICATION_ENV === "1"
    });
    verificationEnvironmentEvidence = verificationEnvironment.evidence;
    try {
      if (verificationEnvironment.evidence.status === "failed") {
        return environmentBlockedVerification(input.task.id, verificationEnvironment.evidence.reason);
      }
      return await runVerificationCommands({
        run_id: input.run_id,
        task_id: input.task.id,
        cwd: taskWorktree.path,
        commands
      });
    } finally {
      verificationEnvironment.cleanup();
    }
  });
  phaseTimings.push(verificationTiming);
  const verificationRecords: Array<Record<string, unknown>> = verification.results.map((kernel, index) => {
    const command = commands[index] ?? "";
    const kernelArtifact = writeArtifact(inputRunRoot(input), `kernel/${kernel.request_id}.json`, JSON.stringify(kernel, null, 2));
    artifactIndexEntries.push(artifactIndexEntry({ artifact: kernelArtifact, producer_phase: "verification", task_id: input.task.id }));
    const passed = kernel.exit_code === 0 && !kernel.timed_out;
    return {
      verification_id: kernel.request_id,
      task_id: input.task.id,
      command,
      cwd: taskWorktree.path,
      kernel_result_ref: kernelArtifact.path,
      exit_code: kernel.exit_code,
      timed_out: kernel.timed_out,
      stdout_sha256: kernel.stdout_sha256,
      stderr_sha256: kernel.stderr_sha256,
      status: passed ? "passed" : "failed",
      verification_environment: verificationEnvironmentEvidence,
      failure_class: passed ? null : verification.failure_class,
      failure_summary: passed ? null : verification.failure_summary
    };
  });
  if (verification.results.length === 0 && verification.failure_class) {
    verificationRecords.push({
      verification_id: verification.failed_verification_id,
      task_id: input.task.id,
      command: null,
      cwd: taskWorktree.path,
      kernel_result_ref: null,
      exit_code: null,
      timed_out: false,
      status: "failed",
      verification_environment: verificationEnvironmentEvidence,
      failure_class: verification.failure_class,
      failure_summary: verification.failure_summary
    });
  }
  const providerEnvironmentBlockerOverridden =
    verification.status === "passed" && isProviderEnvironmentSelfReport(worker.failure_class);
  if (providerEnvironmentBlockerOverridden) {
    workerEvent.outcome = "success";
    workerEvent.summary = `${worker.summary} Kernel verification passed; provider environment self-report was kept as evidence.`;
    workerEvent.payload = {
      task_id: input.task.id,
      failure_class: null,
      provider_reported_failure_class: worker.failure_class ?? null,
      worker,
      attempt
    };
    workerEvent.trust_impact = "supports_success";
  }
  const providerAccepted = worker.status === "completed" || providerEnvironmentBlockerOverridden;
  const verificationPassed = verification.status === "passed" && providerAccepted;
  const verificationFailureClass = verification.failure_class ?? (verificationPassed ? null : worker.failure_class ?? "verification_failed");
  events.push({
    run_id: input.run_id,
    event_type: "runway.verification_result",
    phase: "verify",
    outcome: verificationPassed ? "success" : "failed",
    summary: verificationPassed
      ? "Verification passed with kernel evidence."
      : verification.failure_summary ?? "Verification failed with kernel evidence.",
    payload: {
      task_id: input.task.id,
      failure_class: verificationFailureClass,
      failure_summary: verification.failure_summary,
      worker,
      verification: verificationRecords,
      checkpoint_ref: null
    },
    trust_impact: verificationPassed ? "supports_success" : "supports_failure"
  });

  let latestFailureClass: FailureClass | null = verificationPassed ? null : verificationFailureClass ?? "verification_failed";
  const checkpointRefs: string[] = [];
  if (verificationPassed) {
    const scopeValidation = validateDiffScope({
      actual_changed_files: listActualChangedFiles(taskWorktree.path),
      claimed_changed_files: worker.changed_files,
      allowed_write_globs: writableClaimPaths(input.task),
      forbidden_write_globs: [".git/**", "node_modules/**"]
    });
    if (!scopeValidation.ok) {
      latestFailureClass = "diff_scope_failed";
      events.push({
        run_id: input.run_id,
        event_type: "runway.diff_scope_result",
        phase: "verify",
        outcome: "blocked",
        summary: "Diff scope validation blocked checkpoint creation.",
        payload: {
          task_id: input.task.id,
          failure_class: scopeValidation.failure_class,
          reason: scopeValidation.reason,
          changed_files: scopeValidation.changed_files
        },
        trust_impact: "supports_failure"
      });
    }
    const debugDenials = debugArtifactDenials(input.task.id, scopeValidation.ok ? scopeValidation.changed_files : []);
    if (debugDenials.length > 0) {
      latestFailureClass = "diff_scope_failed";
      for (const denial of debugDenials) {
        events.push({
          run_id: input.run_id,
          event_type: "kernel.hook_denied",
          phase: "hook",
          outcome: "blocked",
          summary: denial.reason,
          payload: { task_id: input.task.id, denial },
          trust_impact: "requires_review"
        });
      }
    }
    const verified = !scopeValidation.ok
      || debugDenials.length > 0
      ? { merged: false }
      : mergeCandidate({ task_id: input.task.id, candidate_id: worker.candidate_id, reviewed: true, verified: true });
    if (verified.merged && writableClaimPaths(input.task).length > 0 && scopeValidation.ok) {
      const { value: checkpoint, timing: checkpointTiming } = await measurePhase("checkpoint", () => createCheckpointArtifact({
        run_root: inputRunRoot(input),
        run_id: input.run_id,
        task_id: input.task.id,
        candidate_id: worker.candidate_id,
        worktree_path: taskWorktree.path,
        changed_files: scopeValidation.changed_files,
        verification_refs: verificationRecords.map((record) => String(record.kernel_result_ref))
      }));
      phaseTimings.push(checkpointTiming);
      artifactIndexEntries.push(
        artifactIndexEntry({
          artifact: {
            path: checkpoint.patch_ref,
            sha256: checkpoint.patch_sha256,
            byte_length: checkpoint.patch_byte_length,
            media_type: "text/x-diff"
          },
          producer_phase: "checkpoint",
          task_id: input.task.id
        })
      );
      const { value: dryRun, timing: dryRunTiming } = await measurePhase("checkpoint_dry_run", () => dryRunCheckpointPatch({
        run_root: inputRunRoot(input),
        checkpoint_ref: checkpoint.manifest_ref,
        source: input.workspace,
        base_checkpoint_refs: input.checkpoint_inputs
      }));
      phaseTimings.push(dryRunTiming);
      artifactIndexEntries.push(
        artifactIndexEntry({
          artifact: artifactReferenceFromRunRef(inputRunRoot(input), checkpoint.manifest_ref, "application/json"),
          producer_phase: "checkpoint",
          task_id: input.task.id
        }),
        artifactIndexEntry({ artifact: dryRun.evidence_artifact, producer_phase: "checkpoint_dry_run", task_id: input.task.id })
      );
      events.push({
        run_id: input.run_id,
        event_type: "runway.checkpoint_created",
        phase: "checkpoint",
        outcome: "success",
        summary: "Verified checkpoint artifact created.",
        payload: {
          task_id: input.task.id,
          candidate_id: worker.candidate_id,
          checkpoint_ref: checkpoint.manifest_ref,
          patch_ref: checkpoint.patch_ref
        }
      });
      events.push({
        run_id: input.run_id,
        event_type: "runway.apply_dry_run_result",
        phase: "checkpoint",
        outcome: dryRun.status === "passed" ? "success" : "blocked",
        summary: dryRun.status === "passed"
          ? "Checkpoint patch dry-run passed."
          : dryRun.failure_class === "needs_rebase"
            ? "Checkpoint patch dry-run failed against current source."
            : "Checkpoint patch dry-run failed.",
        payload: {
          task_id: input.task.id,
          checkpoint_ref: checkpoint.manifest_ref,
          dry_run: dryRun,
          ...(dryRun.status === "failed" ? {
            reason: dryRun.reason ?? "patch_dry_run_failed",
            failure_class: dryRun.failure_class ?? "unsafe_apply",
            failed_files: dryRun.failed_files ?? []
          } : {})
        }
      });
      if (dryRun.status === "passed") {
        checkpointRefs.push(checkpoint.manifest_ref);
      } else {
        latestFailureClass = dryRun.failure_class ?? "unsafe_apply";
      }
    } else if (scopeValidation.ok && debugDenials.length === 0) {
      latestFailureClass = "missing_checkpoint";
    }
  }

  const completed = new Date().toISOString();
  const totalTiming: ExecutionPhaseTiming = {
    phase: "total",
    started,
    completed,
    duration_ms: Math.round(performance.now() - startedAtMs)
  };
  return {
    task_id: input.task.id,
    status: verificationPassed && latestFailureClass === null ? "verified" : "blocked",
    latest_failure_class: latestFailureClass,
    worktree_manifest: worktreeManifest,
    task_packet_path: packetPath,
    task_packet_sha256: packetArtifact.sha256,
    provider_attempt: attempt,
    verification_records: verificationRecords,
    checkpoint_refs: checkpointRefs,
    artifact_index_entries: artifactIndexEntries,
    events,
    timing: { started, completed, duration_ms: totalTiming.duration_ms ?? 0 },
    phase_timings: [...phaseTimings, totalTiming],
    worker_result: worker
  };
}

function environmentBlockedVerification(taskId: string, reason: string | null): VerificationRunOutput {
  return {
    status: "failed",
    results: [],
    failure_class: "environment_blocker",
    failure_summary: reason ? `verification environment setup failed: ${reason}` : "verification environment setup failed",
    failed_verification_id: `verify_${taskId}_environment`
  };
}

function hookDeniedResult(input: {
  input: ExecuteWaygentTaskInput;
  started: string;
  startedAtMs: number;
  worktreeManifest: WaygentWorktreeManifest;
  packetPath: string;
  packetSha256: string;
  phaseTimings: ExecutionPhaseTiming[];
  artifactIndexEntries: ArtifactIndexEntry[];
  stdinRef: string;
  attemptId: string;
  attemptStarted: string;
  denials: HookDenial[];
}): WaygentTaskExecutionResult {
  const completed = new Date().toISOString();
  const worker: WorkerResult = {
    schema: "runway.worker_result.v1",
    task_id: input.input.task.id,
    candidate_id: `candidate_${input.input.task.id}`,
    status: "blocked",
    changed_files: [],
    summary: "Runtime hook denied provider dispatch.",
    evidence: { hook_denials: input.denials },
    failure_class: "permission_denied"
  };
  const workerArtifact = writeArtifact(inputRunRoot(input.input), `worker/${input.input.task.id}.json`, JSON.stringify(worker, null, 2));
  const stdoutArtifact = writeArtifact(inputRunRoot(input.input), `provider/${input.attemptId}.stdout.txt`, JSON.stringify(worker), "text/plain");
  const stderrArtifact = writeArtifact(inputRunRoot(input.input), `provider/${input.attemptId}.stderr.txt`, "", "text/plain");
  input.artifactIndexEntries.push(
    artifactIndexEntry({ artifact: workerArtifact, producer_phase: "provider", task_id: input.input.task.id }),
    artifactIndexEntry({ artifact: stdoutArtifact, producer_phase: "provider", task_id: input.input.task.id }),
    artifactIndexEntry({ artifact: stderrArtifact, producer_phase: "provider", task_id: input.input.task.id })
  );
  const attempt: ProviderAttempt = {
    schema: "runway.provider_attempt.v1",
    attempt_id: input.attemptId,
    run_id: input.input.run_id,
    task_id: input.input.task.id,
    role: "implement",
    provider: input.input.provider,
    command: ["hook-denied"],
    cwd: input.worktreeManifest.path,
    stdin_ref: input.stdinRef,
    stdout_ref: stdoutArtifact.path,
    stderr_ref: stderrArtifact.path,
    event_stream_ref: null,
    exit_code: 1,
    timed_out: false,
    started_at: input.attemptStarted,
    completed_at: completed,
    worker_result_ref: workerArtifact.path,
    failure_class: "permission_denied",
    ...(input.input.requested_model ? { requested_model: input.input.requested_model } : {}),
    actual_model: { model: null, reasoning: null, source: "unknown" },
    usage: null,
    usage_source: "unknown"
  };
  const events: TaskExecutionEventIntent[] = [
    ...input.denials.map((denial) => ({
      run_id: input.input.run_id,
      event_type: "kernel.hook_denied",
      phase: "hook",
      outcome: "blocked" as const,
      summary: denial.reason,
      payload: { task_id: input.input.task.id, denial },
      trust_impact: "requires_review" as const
    })),
    {
      run_id: input.input.run_id,
      event_type: "runway.worker_result",
      phase: "worker",
      outcome: "failed",
      summary: worker.summary,
      payload: { task_id: input.input.task.id, failure_class: "permission_denied", worker, attempt },
      trust_impact: "supports_failure"
    }
  ];
  const totalTiming: ExecutionPhaseTiming = {
    phase: "total",
    started: input.started,
    completed,
    duration_ms: Math.round(performance.now() - input.startedAtMs)
  };
  return {
    task_id: input.input.task.id,
    status: "blocked",
    latest_failure_class: "permission_denied",
    worktree_manifest: input.worktreeManifest,
    task_packet_path: input.packetPath,
    task_packet_sha256: input.packetSha256,
    provider_attempt: attempt,
    verification_records: [],
    checkpoint_refs: [],
    artifact_index_entries: input.artifactIndexEntries,
    events,
    timing: { started: input.started, completed, duration_ms: totalTiming.duration_ms ?? 0 },
    phase_timings: [...input.phaseTimings, totalTiming],
    worker_result: worker
  };
}

async function measurePhase<T>(
  phase: ExecutionPhaseTiming["phase"],
  run: () => Promise<T> | T
): Promise<{ value: T; timing: ExecutionPhaseTiming }> {
  const startedAtMs = performance.now();
  const started = new Date().toISOString();
  const value = await run();
  const completed = new Date().toISOString();
  return {
    value,
    timing: { phase, started, completed, duration_ms: Math.round(performance.now() - startedAtMs) }
  };
}

function artifactReferenceFromRunRef(runRoot: string, ref: string, mediaType: string) {
  const bytes = readFileSync(join(runRoot, ref));
  return {
    path: ref,
    sha256: sha256(bytes),
    byte_length: bytes.byteLength,
    media_type: mediaType
  };
}

function inputRunRoot(input: Pick<ExecuteWaygentTaskInput, "root" | "run_id">): string {
  return join(input.root, input.run_id);
}

function createProviderAdapter(
  provider: ProviderName,
  processes: ExecuteWaygentTaskInput["provider_processes"] = {}
): ProviderAdapter {
  if (provider === "codex") return new CodexProviderAdapter(processes.codex);
  if (provider === "claude") return new ClaudeProviderAdapter(processes.claude);
  return new FakeProviderAdapter();
}

function normalizeProviderRunResult(
  result: WorkerResult | ProviderAdapterRunResult
): { worker: WorkerResult; processEvidence?: ProviderProcessEvidence; metadata?: ProviderRunMetadata } {
  if (typeof result === "object" && result !== null && "worker" in result) {
    return {
      worker: result.worker,
      ...("metadata" in result && result.metadata ? { metadata: result.metadata as ProviderRunMetadata } : {}),
      ...(result.process ? { processEvidence: result.process } : {})
    };
  }
  return { worker: result };
}

function isProviderEnvironmentSelfReport(failureClass: FailureClass | undefined): boolean {
  return failureClass === "dependency_missing" || failureClass === "environment_blocker";
}

function materializeCheckpointInputs(input: { run_root: string; worktree: string; checkpoint_refs: string[] }): void {
  for (const checkpointRef of input.checkpoint_refs) {
    const resolved = resolveCheckpointPatch(input.run_root, checkpointRef);
    if (!resolved) throw new Error(`dependency checkpoint cannot be resolved: ${checkpointRef}`);
    if (resolved.patch.trim().length === 0) continue;
    const apply = spawnSync("git", ["apply", "-"], {
      cwd: input.worktree,
      input: resolved.patch,
      encoding: "utf8",
      stdio: ["pipe", "pipe", "pipe"]
    });
    if (apply.status !== 0) {
      throw new Error(`dependency checkpoint apply failed for ${checkpointRef}: ${apply.stderr || apply.stdout}`);
    }
    runGit(input.worktree, ["add", "-A"]);
    const dirtyIndex = spawnSync("git", ["diff", "--cached", "--quiet"], {
      cwd: input.worktree,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"]
    });
    if (dirtyIndex.status === 0) continue;
    if (dirtyIndex.status !== 1) {
      throw new Error(`dependency checkpoint index check failed for ${checkpointRef}: ${dirtyIndex.stderr}`);
    }
    runGit(input.worktree, [
      "-c",
      "user.email=waygent@local",
      "-c",
      "user.name=Waygent",
      "commit",
      "-q",
      "--no-verify",
      "-m",
      `waygent dependency checkpoint ${checkpointRef}`
    ]);
  }
}

function runGit(cwd: string, args: string[]): void {
  const result = spawnSync("git", args, {
    cwd,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (result.status !== 0) throw new Error(`git ${args.join(" ")} failed: ${result.stderr || result.stdout}`);
}

function buildTaskPrompt(task: Pick<ParsedWaygentTask, "title" | "instructions" | "verification_commands"> | undefined, taskPacketPath?: string): string {
  if (!task) return "Waygent task";
  return [
    taskPlanExcerpt(task),
    taskPacketPath ? `task_packet_path: ${taskPacketPath}` : null,
    "Verify:",
    task.verification_commands.join("\n")
  ].filter(Boolean).join("\n\n");
}

function taskPlanExcerpt(task: Pick<ParsedWaygentTask, "title" | "instructions">): string {
  return task.instructions.length > 0
    ? [task.title, ...task.instructions].join("\n")
    : task.title;
}

function materializeFakeProviderResult(worktree: string, task: ParsedWaygentTask): void {
  for (const claim of task.file_claims.filter((item) => item.mode !== "read_only")) {
    const target = join(worktree, claim.path);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, `Waygent fake provider output for ${task.id}\n`);
  }
}

function writableClaimPaths(task: ParsedWaygentTask): string[] {
  return task.file_claims.filter((claim) => claim.mode !== "read_only").map((claim) => normalizeClaimPath(claim.path));
}

function normalizeClaimPath(path: string): string {
  return isAbsolute(path) ? path : path.replace(/^\.\/+/, "");
}
