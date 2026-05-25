import { spawnSync } from "node:child_process";
import { mkdirSync, existsSync, rmSync } from "node:fs";
import { dirname } from "node:path";

export interface PrepareRepairWorktreeInput {
  source_repo: string;
  destination: string;
  base_branch: string;
  prior_patch_path: string;
}

export type PrepareRepairWorktreeResult =
  | { status: "ready"; destination: string }
  | { status: "blocked"; reason: "prior_patch_apply_failed" | "worktree_create_failed" };

export function prepareRepairWorktree(input: PrepareRepairWorktreeInput): PrepareRepairWorktreeResult {
  mkdirSync(dirname(input.destination), { recursive: true });
  if (existsSync(input.destination)) {
    rmSync(input.destination, { recursive: true, force: true });
  }
  const create = spawnSync(
    "git",
    ["worktree", "add", "--detach", input.destination, input.base_branch],
    { cwd: input.source_repo, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
  );
  if (create.status !== 0) {
    return { status: "blocked", reason: "worktree_create_failed" };
  }
  const check = spawnSync(
    "git",
    ["apply", "--check", input.prior_patch_path],
    { cwd: input.destination, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
  );
  if (check.status !== 0) {
    spawnSync("git", ["worktree", "remove", "--force", input.destination], { cwd: input.source_repo });
    return { status: "blocked", reason: "prior_patch_apply_failed" };
  }
  const apply = spawnSync(
    "git",
    ["apply", input.prior_patch_path],
    { cwd: input.destination, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
  );
  if (apply.status !== 0) {
    spawnSync("git", ["worktree", "remove", "--force", input.destination], { cwd: input.source_repo });
    return { status: "blocked", reason: "prior_patch_apply_failed" };
  }
  return { status: "ready", destination: input.destination };
}
