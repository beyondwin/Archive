import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { describe, expect, test } from "bun:test";
import {
  createCombinedCheckpointPatchArtifact,
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

function createCheckpointFixture(prefix: string) {
  const source = initRepo(`${prefix}source-`);
  const runRoot = mkdtempSync(join(tmpdir(), `${prefix}run-`));
  const worktreeA = cloneWorktree(source, `${prefix}a-`);
  const worktreeB = cloneWorktree(source, `${prefix}b-`);
  writeFileSync(join(worktreeA, "a.txt"), `${"a\n".repeat(100_000)}`);
  writeFileSync(join(worktreeB, "b.txt"), `${"b\n".repeat(100_000)}`);
  return { source, runRoot, worktreeA, worktreeB };
}

async function dryRunCheckpointPatchInChild(input: { run_root: string; checkpoint_ref: string; source: string }) {
  const checkpointArtifactsUrl = pathToFileURL(join(import.meta.dir, "../src/checkpointArtifacts.ts")).href;
  const child = Bun.spawn(
    [
      process.execPath,
      "--eval",
      `
        const { dryRunCheckpointPatch } = await import(${JSON.stringify(checkpointArtifactsUrl)});
        const result = dryRunCheckpointPatch(${JSON.stringify(input)});
        console.log(JSON.stringify(result));
        if (result.status !== "passed") process.exit(1);
      `
    ],
    {
      stdout: "pipe",
      stderr: "pipe"
    }
  );
  const [exitCode, stdout, stderr] = await Promise.all([
    child.exited,
    new Response(child.stdout).text(),
    new Response(child.stderr).text()
  ]);
  if (exitCode !== 0) {
    throw new Error(`checkpoint dry-run child failed: ${stderr || stdout}`);
  }
  return JSON.parse(stdout) as ReturnType<typeof dryRunCheckpointPatch>;
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

  test("treats empty checkpoint patches as verified no-op evidence", () => {
    const runRoot = mkdtempSync(join(tmpdir(), "waygent-checkpoint-noop-run-"));
    const source = initRepo("waygent-checkpoint-noop-source-");
    const worktree = cloneWorktree(source, "waygent-checkpoint-noop-worktree-");

    const checkpoint = createCheckpointArtifact({
      run_root: runRoot,
      run_id: "run_noop",
      task_id: "task_noop",
      candidate_id: "candidate_noop",
      worktree_path: worktree,
      changed_files: [],
      verification_refs: []
    });

    expect(readFileSync(join(runRoot, checkpoint.patch_ref), "utf8")).toBe("");
    const dryRun = dryRunCheckpointPatch({
      run_root: runRoot,
      checkpoint_ref: checkpoint.manifest_ref,
      source
    });
    expect(dryRun).toMatchObject({ status: "passed", no_op: true });
    expect(readFileSync(join(runRoot, dryRun.evidence_ref), "utf8")).toContain('"no_op": true');
    expect(readCheckpointManifest(runRoot, checkpoint.manifest_ref)).toMatchObject({
      dry_run_status: "passed",
      dry_run_evidence_ref: dryRun.evidence_ref
    });
  });

  test("treats empty combined apply patches as passed no-op evidence", () => {
    const runRoot = mkdtempSync(join(tmpdir(), "waygent-combined-noop-run-"));
    const source = initRepo("waygent-combined-noop-source-");
    const worktree = cloneWorktree(source, "waygent-combined-noop-worktree-");
    const checkpoint = createCheckpointArtifact({
      run_root: runRoot,
      run_id: "run_combined_noop",
      task_id: "task_combined_noop",
      candidate_id: "candidate_combined_noop",
      worktree_path: worktree,
      changed_files: [],
      verification_refs: []
    });
    dryRunCheckpointPatch({ run_root: runRoot, checkpoint_ref: checkpoint.manifest_ref, source });

    const combined = createCombinedCheckpointPatchArtifact({
      run_root: runRoot,
      run_id: "run_combined_noop",
      checkpoint_refs: [checkpoint.manifest_ref],
      source
    });

    expect(combined).toMatchObject({ status: "passed", patch_byte_length: 0, no_op: true });
    expect(readFileSync(join(runRoot, combined.evidence_ref), "utf8")).toContain('"no_op": true');
  });

  test("checkpoint dry-runs use unique scratch files and can run concurrently", async () => {
    const fixture = createCheckpointFixture("waygent-parallel-dry-run-");
    const first = createCheckpointArtifact({
      run_root: fixture.runRoot,
      run_id: "run_parallel_dry_run",
      task_id: "task_a",
      candidate_id: "candidate_a",
      worktree_path: fixture.worktreeA,
      changed_files: ["a.txt"],
      verification_refs: []
    });
    const second = createCheckpointArtifact({
      run_root: fixture.runRoot,
      run_id: "run_parallel_dry_run",
      task_id: "task_b",
      candidate_id: "candidate_b",
      worktree_path: fixture.worktreeB,
      changed_files: ["b.txt"],
      verification_refs: []
    });

    const sourceScratchPath = join(fixture.source, ".waygent-dry-run.patch");
    let sourceScratchObserved = false;
    let watching = true;
    const sourceScratchWatcher = (async () => {
      while (watching && !sourceScratchObserved) {
        sourceScratchObserved = existsSync(sourceScratchPath);
        await Bun.sleep(1);
      }
    })();

    const [firstDryRun, secondDryRun] = await Promise.all([
      dryRunCheckpointPatchInChild({
        run_root: fixture.runRoot,
        checkpoint_ref: first.manifest_ref,
        source: fixture.source
      }),
      dryRunCheckpointPatchInChild({
        run_root: fixture.runRoot,
        checkpoint_ref: second.manifest_ref,
        source: fixture.source
      })
    ]).finally(async () => {
      watching = false;
      await sourceScratchWatcher;
    });

    expect(firstDryRun.status).toBe("passed");
    expect(secondDryRun.status).toBe("passed");
    expect(firstDryRun.evidence_ref).not.toBe(secondDryRun.evidence_ref);
    expect(readCheckpointManifest(fixture.runRoot, first.manifest_ref)).toMatchObject({
      dry_run_status: "passed",
      dry_run_evidence_ref: firstDryRun.evidence_ref
    });
    expect(readCheckpointManifest(fixture.runRoot, second.manifest_ref)).toMatchObject({
      dry_run_status: "passed",
      dry_run_evidence_ref: secondDryRun.evidence_ref
    });
    expect(sourceScratchObserved).toBe(false);
    expect(existsSync(sourceScratchPath)).toBe(false);
  });
});
