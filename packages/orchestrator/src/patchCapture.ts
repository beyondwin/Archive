import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";

export interface CapturedPatch {
  patch: string;
  sha256: string;
  byteLength: number;
  truncatedWarning: boolean;
}

const PATCH_WARN_BYTES = 1_048_576;

export interface CaptureInput {
  worktree: string;
  base: string;
}

export function captureWorktreePatch(input: CaptureInput): CapturedPatch | null {
  const args = ["diff", input.base, "--binary"];
  const result = spawnSync("git", args, {
    cwd: input.worktree,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.status !== 0) {
    throw new Error(
      `captureWorktreePatch git diff failed (exit ${result.status}): ${result.stderr}`,
    );
  }
  if (!result.stdout || result.stdout.length === 0) return null;
  const patch = result.stdout;
  const byteLength = Buffer.byteLength(patch);
  return {
    patch,
    sha256: createHash("sha256").update(patch).digest("hex"),
    byteLength,
    truncatedWarning: byteLength > PATCH_WARN_BYTES,
  };
}
