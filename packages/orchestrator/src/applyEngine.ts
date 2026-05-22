import { spawnSync } from "node:child_process";
import { rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { runVerificationCommands } from "./verification";
import type { VerificationRunOutput } from "./verification";

export interface ApplyVerifiedCheckpointInput {
  source: string;
  patch: string;
  post_apply_commands: string[];
}

export interface ApplyVerifiedCheckpointOutput {
  status: "applied" | "blocked" | "failed";
  reason?: string;
  post_apply_verification?: PostApplyVerificationSummary;
}

export interface PostApplyVerificationSummary {
  status: VerificationRunOutput["status"];
  failure_class: VerificationRunOutput["failure_class"];
  failure_summary: VerificationRunOutput["failure_summary"];
  failed_verification_id: VerificationRunOutput["failed_verification_id"];
  failed_commands: Array<{
    request_id: string;
    command: string;
    exit_code: number | null;
    timed_out: boolean;
    stdout_snippet: string;
    stderr_snippet: string;
  }>;
}

export async function applyVerifiedCheckpoint(input: ApplyVerifiedCheckpointInput): Promise<ApplyVerifiedCheckpointOutput> {
  const status = spawnSync("git", ["status", "--porcelain"], { cwd: input.source, encoding: "utf8" });
  if (status.status !== 0 || status.stdout.trim()) return { status: "blocked", reason: "dirty_source_checkout" };
  if (input.patch.trim().length === 0) {
    const verification = await runVerificationCommands({
      run_id: "apply",
      task_id: "post_apply",
      cwd: input.source,
      commands: input.post_apply_commands
    });
    if (verification.status !== "passed") {
      return {
        status: "failed",
        reason: "post_apply_verification_failed",
        post_apply_verification: summarizePostApplyVerification(verification, input.post_apply_commands)
      };
    }
    return { status: "applied" };
  }
  const patchPath = join(input.source, ".waygent-apply.patch");
  writeFileSync(patchPath, input.patch);
  const dryRun = spawnSync("git", ["apply", "--check", patchPath], { cwd: input.source, encoding: "utf8" });
  if (dryRun.status !== 0) {
    rmSync(patchPath, { force: true });
    return { status: "blocked", reason: "patch_dry_run_failed" };
  }
  const apply = spawnSync("git", ["apply", patchPath], { cwd: input.source, encoding: "utf8" });
  rmSync(patchPath, { force: true });
  if (apply.status !== 0) return { status: "failed", reason: "patch_apply_failed" };
  const verification = await runVerificationCommands({
    run_id: "apply",
    task_id: "post_apply",
    cwd: input.source,
    commands: input.post_apply_commands
  });
  if (verification.status !== "passed") {
    return {
      status: "failed",
      reason: "post_apply_verification_failed",
      post_apply_verification: summarizePostApplyVerification(verification, input.post_apply_commands)
    };
  }
  return { status: "applied" };
}

function summarizePostApplyVerification(
  verification: VerificationRunOutput,
  commands: string[]
): PostApplyVerificationSummary {
  return {
    status: verification.status,
    failure_class: verification.failure_class,
    failure_summary: verification.failure_summary,
    failed_verification_id: verification.failed_verification_id,
    failed_commands: verification.results
      .map((result, index) => ({ result, command: commands[index] ?? result.request_id }))
      .filter(({ result }) => result.exit_code !== 0 || result.timed_out)
      .map(({ result, command }) => ({
        request_id: result.request_id,
        command,
        exit_code: result.exit_code,
        timed_out: result.timed_out,
        stdout_snippet: outputSnippet(result.stdout),
        stderr_snippet: outputSnippet(result.stderr)
      }))
  };
}

function outputSnippet(output: string): string {
  const trimmed = output.trim();
  return trimmed.length > 1000 ? `${trimmed.slice(0, 1000)}...` : trimmed;
}
