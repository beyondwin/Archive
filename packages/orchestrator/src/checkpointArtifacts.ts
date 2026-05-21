import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { sha256, writeArtifact } from "@waygent/lens-store";

export interface CheckpointManifest {
  schema: "waygent.checkpoint_manifest.v1";
  run_id: string;
  task_id: string;
  candidate_id: string;
  patch_ref: string;
  patch_sha256: string;
  patch_byte_length: number;
  changed_files: string[];
  source_base: string | null;
  worktree_path: string;
  verification_refs: string[];
  created_at: string;
  dry_run_status: "not_run" | "passed" | "failed";
  dry_run_evidence_ref: string | null;
}

export interface CreateCheckpointArtifactInput {
  run_root: string;
  run_id: string;
  task_id: string;
  candidate_id: string;
  worktree_path: string;
  changed_files: string[];
  verification_refs: string[];
}

export interface CreatedCheckpointArtifact {
  status: "created";
  manifest_ref: string;
  patch_ref: string;
  patch_sha256: string;
  patch_byte_length: number;
}

export interface CheckpointValidationResult {
  ok: boolean;
  patch_ref?: string;
  reason?: "checkpoint_manifest_missing" | "checkpoint_patch_missing" | "checkpoint_digest_mismatch";
}

export interface CheckpointDryRunResult {
  status: "passed" | "failed";
  reason?: "checkpoint_unresolvable" | "patch_dry_run_failed";
  evidence_ref: string;
}

export function createCheckpointArtifact(input: CreateCheckpointArtifactInput): CreatedCheckpointArtifact {
  markUntrackedFilesForDiff(input.worktree_path, input.changed_files);
  const diff = spawnSync("git", ["diff", "--binary"], {
    cwd: input.worktree_path,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (diff.status !== 0) {
    throw new Error(`failed to create checkpoint diff for ${input.task_id}: ${diff.stderr}`);
  }

  const patchArtifact = writeArtifact(
    input.run_root,
    `checkpoints/${input.task_id}/${input.candidate_id}.patch`,
    diff.stdout,
    "text/x-diff"
  );
  const manifest: CheckpointManifest = {
    schema: "waygent.checkpoint_manifest.v1",
    run_id: input.run_id,
    task_id: input.task_id,
    candidate_id: input.candidate_id,
    patch_ref: patchArtifact.path,
    patch_sha256: patchArtifact.sha256,
    patch_byte_length: patchArtifact.byte_length,
    changed_files: input.changed_files,
    source_base: currentHead(input.worktree_path),
    worktree_path: input.worktree_path,
    verification_refs: input.verification_refs,
    created_at: new Date().toISOString(),
    dry_run_status: "not_run",
    dry_run_evidence_ref: null
  };
  const manifestArtifact = writeArtifact(
    input.run_root,
    `checkpoints/${input.task_id}/${input.candidate_id}.json`,
    `${JSON.stringify(manifest, null, 2)}\n`
  );

  return {
    status: "created",
    manifest_ref: manifestArtifact.path,
    patch_ref: patchArtifact.path,
    patch_sha256: patchArtifact.sha256,
    patch_byte_length: patchArtifact.byte_length
  };
}

export function readCheckpointManifest(runRoot: string, checkpointRef: string): CheckpointManifest {
  return JSON.parse(readFileSync(resolveRunArtifactPath(runRoot, checkpointRef), "utf8")) as CheckpointManifest;
}

export function validateCheckpointManifest(runRoot: string, checkpointRef: string): CheckpointValidationResult {
  const manifestPath = resolveRunArtifactPath(runRoot, checkpointRef);
  if (!existsSync(manifestPath)) return { ok: false, reason: "checkpoint_manifest_missing" };
  let manifest: CheckpointManifest;
  try {
    manifest = readCheckpointManifest(runRoot, checkpointRef);
  } catch {
    return { ok: false, reason: "checkpoint_manifest_missing" };
  }
  const patchPath = resolveRunArtifactPath(runRoot, manifest.patch_ref);
  if (!existsSync(patchPath)) return { ok: false, reason: "checkpoint_patch_missing" };
  const patch = readFileSync(patchPath);
  if (sha256(patch) !== manifest.patch_sha256 || patch.byteLength !== manifest.patch_byte_length) {
    return { ok: false, reason: "checkpoint_digest_mismatch" };
  }
  return { ok: true, patch_ref: manifest.patch_ref };
}

export function resolveCheckpointPatch(runRoot: string, checkpointRef: string): { manifest: CheckpointManifest; patch: string } | null {
  const validation = validateCheckpointManifest(runRoot, checkpointRef);
  if (!validation.ok) return null;
  const manifest = readCheckpointManifest(runRoot, checkpointRef);
  return {
    manifest,
    patch: readFileSync(resolveRunArtifactPath(runRoot, manifest.patch_ref), "utf8")
  };
}

export function dryRunCheckpointPatch(input: { run_root: string; checkpoint_ref: string; source: string }): CheckpointDryRunResult {
  const resolved = resolveCheckpointPatch(input.run_root, input.checkpoint_ref);
  if (!resolved) {
    const evidence = writeCheckpointDryRunEvidence(input.run_root, input.checkpoint_ref, {
      status: "failed",
      reason: "checkpoint_unresolvable"
    });
    return { status: "failed", reason: "checkpoint_unresolvable", evidence_ref: evidence };
  }

  const patchPath = join(input.source, ".waygent-dry-run.patch");
  writeFileSync(patchPath, resolved.patch);
  const dryRun = spawnSync("git", ["apply", "--check", patchPath], {
    cwd: input.source,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  rmSync(patchPath, { force: true });

  const status = dryRun.status === 0 ? "passed" : "failed";
  const evidence = writeCheckpointDryRunEvidence(input.run_root, input.checkpoint_ref, {
    status,
    stdout: dryRun.stdout,
    stderr: dryRun.stderr
  });
  updateCheckpointManifestDryRun(input.run_root, input.checkpoint_ref, status, evidence);

  return {
    status,
    ...(status === "failed" ? { reason: "patch_dry_run_failed" as const } : {}),
    evidence_ref: evidence
  };
}

export function resolveRunArtifactPath(runRoot: string, ref: string): string {
  return isAbsolute(ref) ? ref : join(runRoot, ref);
}

function writeCheckpointDryRunEvidence(runRoot: string, checkpointRef: string, payload: Record<string, unknown>): string {
  const evidence = writeArtifact(
    runRoot,
    `checkpoints/dry-run-${Date.now()}-${Math.random().toString(16).slice(2)}.json`,
    `${JSON.stringify({ checkpoint_ref: checkpointRef, ...payload }, null, 2)}\n`
  );
  return evidence.path;
}

function updateCheckpointManifestDryRun(
  runRoot: string,
  checkpointRef: string,
  status: "passed" | "failed",
  evidenceRef: string
): void {
  const manifestPath = resolveRunArtifactPath(runRoot, checkpointRef);
  if (!existsSync(manifestPath)) return;
  const manifest = readCheckpointManifest(runRoot, checkpointRef);
  writeFileSync(manifestPath, `${JSON.stringify({
    ...manifest,
    dry_run_status: status,
    dry_run_evidence_ref: evidenceRef
  }, null, 2)}\n`);
}

function currentHead(worktree: string): string | null {
  const head = spawnSync("git", ["rev-parse", "HEAD"], {
    cwd: worktree,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"]
  });
  return head.status === 0 ? head.stdout.trim() : null;
}

function markUntrackedFilesForDiff(worktree: string, changedFiles: string[]): void {
  const files = changedFiles.length > 0 ? changedFiles : listUntrackedFiles(worktree);
  if (files.length === 0) return;
  spawnSync("git", ["add", "-N", "--", ...files], {
    cwd: worktree,
    encoding: "utf8",
    stdio: ["ignore", "ignore", "ignore"]
  });
}

function listUntrackedFiles(worktree: string): string[] {
  const result = spawnSync("git", ["ls-files", "--others", "--exclude-standard"], {
    cwd: worktree,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"]
  });
  if (result.status !== 0) return [];
  return result.stdout.split("\n").map((line) => line.trim()).filter(Boolean);
}
