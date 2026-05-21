import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, rmSync } from "node:fs";
import { dirname } from "node:path";
import type { ExecutionPhaseTiming, WaygentWorktreeManifest } from "@waygent/contracts";
import { buildWorktreeManifest, planWorktree } from "@waygent/kernel-client";

export interface PrepareManagedTaskWorktreeInput {
  run_id: string;
  task_id: string;
  workspace: string;
  worktree_root: string;
}

export interface PreparedManagedTaskWorktree {
  manifest: WaygentWorktreeManifest;
  timing: ExecutionPhaseTiming;
}

export function prepareManagedTaskWorktree(input: PrepareManagedTaskWorktreeInput): PreparedManagedTaskWorktree {
  const startedAtMs = performance.now();
  const started = new Date().toISOString();
  const taskWorktree = planWorktree({
    run_id: input.run_id,
    task_id: input.task_id,
    workspace: input.workspace,
    worktree_root: input.worktree_root
  });
  prepareTaskWorktree(input.workspace, taskWorktree.path);
  const completed = new Date().toISOString();
  return {
    manifest: buildWorktreeManifest({
      ...taskWorktree,
      task_id: input.task_id,
      source_commit: currentGitHead(input.workspace)
    }),
    timing: {
      phase: "worktree_setup",
      started,
      completed,
      duration_ms: Math.round(performance.now() - startedAtMs)
    }
  };
}

export function currentGitHead(workspace: string): string | null {
  const head = spawnSync("git", ["rev-parse", "HEAD"], {
    cwd: workspace,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"]
  });
  return head.status === 0 ? head.stdout.trim() : null;
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
