import { spawnSync } from "node:child_process";
import { rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { runVerificationCommands } from "./verification";

export interface ApplyVerifiedCheckpointInput {
  source: string;
  patch: string;
  post_apply_commands: string[];
}

export interface ApplyVerifiedCheckpointOutput {
  status: "applied" | "blocked" | "failed";
  reason?: string;
}

export async function applyVerifiedCheckpoint(input: ApplyVerifiedCheckpointInput): Promise<ApplyVerifiedCheckpointOutput> {
  const status = spawnSync("git", ["status", "--porcelain"], { cwd: input.source, encoding: "utf8" });
  if (status.status !== 0 || status.stdout.trim()) return { status: "blocked", reason: "dirty_source_checkout" };
  const patchPath = join(input.source, ".waygent-apply.patch");
  writeFileSync(patchPath, input.patch);
  const apply = spawnSync("git", ["apply", patchPath], { cwd: input.source, encoding: "utf8" });
  rmSync(patchPath, { force: true });
  if (apply.status !== 0) return { status: "failed", reason: "patch_apply_failed" };
  const verification = await runVerificationCommands({
    run_id: "apply",
    task_id: "post_apply",
    cwd: input.source,
    commands: input.post_apply_commands
  });
  if (verification.status !== "passed") return { status: "failed", reason: "post_apply_verification_failed" };
  return { status: "applied" };
}
