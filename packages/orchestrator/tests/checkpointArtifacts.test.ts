import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import {
  createCheckpointArtifact,
  dryRunCheckpointPatch,
  readCheckpointManifest,
  resolveCheckpointPatch,
  validateCheckpointManifest
} from "../src/checkpointArtifacts";

function initRepo(prefix: string): string {
  const repo = mkdtempSync(join(tmpdir(), prefix));
  Bun.spawnSync(["git", "init", "-q"], { cwd: repo });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: repo });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: repo });
  writeFileSync(join(repo, "README.md"), "before\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: repo });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: repo });
  return repo;
}

function cloneWorktree(source: string, prefix: string): string {
  const worktree = mkdtempSync(join(tmpdir(), prefix));
  Bun.spawnSync(["git", "clone", "--quiet", source, worktree]);
  return worktree;
}

describe("checkpoint artifacts", () => {
  test("creates a manifest and patch for a changed worktree", () => {
    const runRoot = mkdtempSync(join(tmpdir(), "waygent-checkpoint-run-"));
    const source = initRepo("waygent-checkpoint-source-");
    const worktree = cloneWorktree(source, "waygent-checkpoint-worktree-");
    writeFileSync(join(worktree, "README.md"), "after\n");

    const checkpoint = createCheckpointArtifact({
      run_root: runRoot,
      run_id: "run_checkpoint",
      task_id: "task_checkpoint",
      candidate_id: "candidate_checkpoint",
      worktree_path: worktree,
      changed_files: ["README.md"],
      verification_refs: ["artifacts/kernel/verify_task_checkpoint_1.json"]
    });

    expect(checkpoint.status).toBe("created");
    expect(checkpoint.manifest_ref).toBe("artifacts/checkpoints/task_checkpoint/candidate_checkpoint.json");
    expect(existsSync(join(runRoot, checkpoint.manifest_ref))).toBe(true);
    expect(existsSync(join(runRoot, checkpoint.patch_ref))).toBe(true);
    expect(readFileSync(join(runRoot, checkpoint.patch_ref), "utf8")).toContain("+after");
    expect(validateCheckpointManifest(runRoot, checkpoint.manifest_ref)).toMatchObject({
      ok: true,
      patch_ref: checkpoint.patch_ref
    });
    expect(resolveCheckpointPatch(runRoot, checkpoint.manifest_ref)?.patch).toContain("+after");
    expect(dryRunCheckpointPatch({
      run_root: runRoot,
      checkpoint_ref: checkpoint.manifest_ref,
      source
    })).toMatchObject({ status: "passed" });
  });

  test("reports digest mismatch without throwing", () => {
    const runRoot = mkdtempSync(join(tmpdir(), "waygent-checkpoint-mismatch-"));
    const source = initRepo("waygent-checkpoint-mismatch-source-");
    const worktree = cloneWorktree(source, "waygent-checkpoint-mismatch-worktree-");
    writeFileSync(join(worktree, "README.md"), "after\n");

    const checkpoint = createCheckpointArtifact({
      run_root: runRoot,
      run_id: "run_mismatch",
      task_id: "task_mismatch",
      candidate_id: "candidate_mismatch",
      worktree_path: worktree,
      changed_files: ["README.md"],
      verification_refs: []
    });
    writeFileSync(join(runRoot, checkpoint.patch_ref), "corrupted\n");

    expect(validateCheckpointManifest(runRoot, checkpoint.manifest_ref)).toMatchObject({
      ok: false,
      reason: "checkpoint_digest_mismatch"
    });
  });

  test("reads existing checkpoint manifests", () => {
    const runRoot = mkdtempSync(join(tmpdir(), "waygent-checkpoint-read-"));
    const source = initRepo("waygent-checkpoint-read-source-");
    const worktree = cloneWorktree(source, "waygent-checkpoint-read-worktree-");
    writeFileSync(join(worktree, "README.md"), "after\n");
    const checkpoint = createCheckpointArtifact({
      run_root: runRoot,
      run_id: "run_read",
      task_id: "task_read",
      candidate_id: "candidate_read",
      worktree_path: worktree,
      changed_files: ["README.md"],
      verification_refs: []
    });

    expect(readCheckpointManifest(runRoot, checkpoint.manifest_ref)).toMatchObject({
      schema: "waygent.checkpoint_manifest.v1",
      task_id: "task_read",
      candidate_id: "candidate_read"
    });
  });

  test("includes untracked changed files in checkpoint patches", () => {
    const runRoot = mkdtempSync(join(tmpdir(), "waygent-checkpoint-untracked-"));
    const source = initRepo("waygent-checkpoint-untracked-source-");
    const worktree = cloneWorktree(source, "waygent-checkpoint-untracked-worktree-");
    writeFileSync(join(worktree, "new-file.txt"), "new content\n");

    const checkpoint = createCheckpointArtifact({
      run_root: runRoot,
      run_id: "run_untracked",
      task_id: "task_untracked",
      candidate_id: "candidate_untracked",
      worktree_path: worktree,
      changed_files: ["new-file.txt"],
      verification_refs: []
    });

    expect(readFileSync(join(runRoot, checkpoint.patch_ref), "utf8")).toContain("new-file.txt");
    expect(dryRunCheckpointPatch({
      run_root: runRoot,
      checkpoint_ref: checkpoint.manifest_ref,
      source
    })).toMatchObject({ status: "passed" });
  });
});
