import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import type {
  AgentLensEvent,
  FailureClass,
  ProviderAttempt,
  ProviderProcessEvidence,
  WaygentWorktreeManifest,
  WorkerResult
} from "@waygent/contracts";
import { buildTaskPacket } from "@waygent/context-packer";
import { buildWorktreeManifest, planWorktree } from "@waygent/kernel-client";
import { writeArtifact } from "@waygent/lens-store";
import {
  ClaudeProviderAdapter,
  CodexProviderAdapter,
  FakeProviderAdapter,
  type ProviderAdapter,
  type ProviderProcessOptions
} from "@waygent/provider-adapters";
import { mergeCandidate } from "@waygent/runway-control";
import { createCheckpointArtifact, dryRunCheckpointPatch } from "./checkpointArtifacts";
import { listActualChangedFiles, validateDiffScope } from "./diffScope";
import type { ProviderName } from "./executionProfile";
import type { ParsedWaygentTask } from "./planParser";
import type { RunEventInput } from "./runEvents";
import { runVerificationCommands } from "./verification";

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
  events: TaskExecutionEventIntent[];
  timing: { started: string; completed: string; duration_ms: number };
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
}

export async function executeWaygentTask(input: ExecuteWaygentTaskInput): Promise<WaygentTaskExecutionResult> {
  const startedAtMs = performance.now();
  const started = new Date().toISOString();
  const taskWorktree = planWorktree({
    run_id: input.run_id,
    task_id: input.task.id,
    workspace: input.workspace,
    worktree_root: input.worktree_root
  });
  const worktreeManifest = buildWorktreeManifest({
    ...taskWorktree,
    task_id: input.task.id,
    source_commit: currentGitHead(input.workspace)
  });
  prepareTaskWorktree(input.workspace, taskWorktree.path);

  const commands = input.task.verification_commands.length > 0 ? input.task.verification_commands : ["printf hello"];
  const packet = buildTaskPacket({
    run_id: input.run_id,
    task: input.task,
    role: "implement",
    plan_excerpt: input.task.title,
    spec_excerpt: input.spec ?? "",
    checkpoint_inputs: input.checkpoint_inputs,
    previous_failures: []
  });
  const packetArtifact = writeArtifact(inputRunRoot(input), `task_packets/${input.task.id}.json`, `${JSON.stringify(packet, null, 2)}\n`);
  const packetPath = join(inputRunRoot(input), packetArtifact.path);
  const prompt = buildTaskPrompt(input.task, packetPath);
  const attemptId = `attempt_${input.task.id}_1`;
  const attemptStarted = new Date().toISOString();
  const stdinArtifact = writeArtifact(inputRunRoot(input), `provider/${attemptId}.stdin.txt`, prompt, "text/plain");
  const provider = createProviderAdapter(input.provider, input.provider_processes);
  const adapterResult = await provider.run({
    task_id: input.task.id,
    candidate_id: `candidate_${input.task.id}`,
    role: "implement",
    prompt,
    task_packet_path: packetPath,
    cwd: taskWorktree.path,
    changed_files: writableClaimPaths(input.task)
  });
  const { worker, processEvidence } = normalizeProviderRunResult(adapterResult);
  const workerArtifact = writeArtifact(inputRunRoot(input), `worker/${input.task.id}.json`, JSON.stringify(worker, null, 2));
  const stdoutArtifact = writeArtifact(inputRunRoot(input), `provider/${attemptId}.stdout.txt`, processEvidence?.stdout ?? JSON.stringify(worker), "text/plain");
  const stderrArtifact = writeArtifact(inputRunRoot(input), `provider/${attemptId}.stderr.txt`, processEvidence?.stderr ?? "", "text/plain");
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
    ...(processEvidence ? { process: processEvidence } : {})
  };
  const events: TaskExecutionEventIntent[] = [{
    run_id: input.run_id,
    event_type: "runway.worker_result",
    phase: "worker",
    outcome: worker.status === "completed" ? "success" : "failed",
    summary: worker.summary,
    payload: { task_id: input.task.id, failure_class: worker.failure_class ?? null, worker, attempt }
  }];

  if (input.provider === "fake") materializeFakeProviderResult(taskWorktree.path, input.task);

  const verification = await runVerificationCommands({
    run_id: input.run_id,
    task_id: input.task.id,
    cwd: taskWorktree.path,
    commands
  });
  const verificationRecords = verification.results.map((kernel, index) => {
    const command = commands[index] ?? "";
    const kernelArtifact = writeArtifact(inputRunRoot(input), `kernel/${kernel.request_id}.json`, JSON.stringify(kernel, null, 2));
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
      status: kernel.exit_code === 0 && !kernel.timed_out ? "passed" : "failed"
    };
  });
  const verificationPassed = verification.status === "passed" && worker.status === "completed";
  events.push({
    run_id: input.run_id,
    event_type: "runway.verification_result",
    phase: "verify",
    outcome: verificationPassed ? "success" : "failed",
    summary: verificationPassed ? "Verification passed with kernel evidence." : "Verification failed with kernel evidence.",
    payload: { task_id: input.task.id, failure_class: worker.failure_class ?? null, worker, verification: verificationRecords, checkpoint_ref: null }
  });

  let latestFailureClass: FailureClass | null = verificationPassed ? null : worker.failure_class ?? "verification_failed";
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
    const verified = !scopeValidation.ok
      ? { merged: false }
      : mergeCandidate({ task_id: input.task.id, candidate_id: worker.candidate_id, reviewed: true, verified: true });
    if (verified.merged && writableClaimPaths(input.task).length > 0 && scopeValidation.ok) {
      const checkpoint = createCheckpointArtifact({
        run_root: inputRunRoot(input),
        run_id: input.run_id,
        task_id: input.task.id,
        candidate_id: worker.candidate_id,
        worktree_path: taskWorktree.path,
        changed_files: scopeValidation.changed_files,
        verification_refs: verificationRecords.map((record) => String(record.kernel_result_ref))
      });
      const dryRun = dryRunCheckpointPatch({
        run_root: inputRunRoot(input),
        checkpoint_ref: checkpoint.manifest_ref,
        source: input.workspace
      });
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
        summary: dryRun.status === "passed" ? "Checkpoint patch dry-run passed." : "Checkpoint patch dry-run failed.",
        payload: { task_id: input.task.id, checkpoint_ref: checkpoint.manifest_ref, dry_run: dryRun }
      });
      if (dryRun.status === "passed") {
        checkpointRefs.push(checkpoint.manifest_ref);
      } else {
        latestFailureClass = "missing_checkpoint";
      }
    } else if (scopeValidation.ok) {
      latestFailureClass = "missing_checkpoint";
    }
  }

  const completed = new Date().toISOString();
  return {
    task_id: input.task.id,
    status: verificationPassed && latestFailureClass !== "diff_scope_failed" ? "verified" : "blocked",
    latest_failure_class: latestFailureClass,
    worktree_manifest: worktreeManifest,
    task_packet_path: packetPath,
    task_packet_sha256: packetArtifact.sha256,
    provider_attempt: attempt,
    verification_records: verificationRecords,
    checkpoint_refs: checkpointRefs,
    events,
    timing: { started, completed, duration_ms: Math.round(performance.now() - startedAtMs) }
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

function buildTaskPrompt(task: { title: string; verification_commands: string[] } | undefined, taskPacketPath?: string): string {
  if (!task) return "Waygent task";
  return [
    task.title,
    taskPacketPath ? `task_packet_path: ${taskPacketPath}` : null,
    "Verify:",
    task.verification_commands.join("\n")
  ].filter(Boolean).join("\n\n");
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

function currentGitHead(worktree: string): string | null {
  const head = spawnSync("git", ["rev-parse", "HEAD"], {
    cwd: worktree,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"]
  });
  return head.status === 0 ? head.stdout.trim() : null;
}

function writableClaimPaths(task: ParsedWaygentTask): string[] {
  return task.file_claims.filter((claim) => claim.mode !== "read_only").map((claim) => normalizeClaimPath(claim.path));
}

function normalizeClaimPath(path: string): string {
  return isAbsolute(path) ? path : path.replace(/^\.\/+/, "");
}
