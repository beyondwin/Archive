import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join } from "node:path";
import type { ArtifactReference } from "@waygent/contracts";
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
  manifest_sha256: string;
  manifest_byte_length: number;
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
  evidence_artifact: ArtifactReference;
}

export interface CombinedCheckpointPatchResult {
  status: "passed" | "failed";
  checkpoint_refs: string[];
  patch_ref?: string;
  patch_sha256?: string;
  patch_byte_length?: number;
  patch_artifact?: ArtifactReference;
  reason?:
    | CheckpointValidationResult["reason"]
    | "missing_verified_checkpoint"
    | "checkpoint_worktree_missing"
    | "patch_materialization_failed"
    | "patch_dry_run_failed";
  evidence_ref: string;
  evidence_artifact: ArtifactReference;
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
    manifest_sha256: manifestArtifact.sha256,
    manifest_byte_length: manifestArtifact.byte_length,
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
    return { status: "failed", reason: "checkpoint_unresolvable", evidence_ref: evidence.path, evidence_artifact: evidence };
  }

  const scratchDir = mkdtempSync(join(tmpdir(), "waygent-checkpoint-dry-run-"));
  const patchPath = join(scratchDir, "candidate.patch");
  try {
    writeFileSync(patchPath, resolved.patch);
    const dryRun = spawnSync("git", ["apply", "--check", patchPath], {
      cwd: input.source,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"]
    });

    const status = dryRun.status === 0 ? "passed" : "failed";
    const evidence = writeCheckpointDryRunEvidence(input.run_root, input.checkpoint_ref, {
      status,
      stdout: dryRun.stdout,
      stderr: dryRun.stderr
    });
    updateCheckpointManifestDryRun(input.run_root, input.checkpoint_ref, status, evidence.path);

    return {
      status,
      ...(status === "failed" ? { reason: "patch_dry_run_failed" as const } : {}),
      evidence_ref: evidence.path,
      evidence_artifact: evidence
    };
  } finally {
    rmSync(scratchDir, { recursive: true, force: true });
  }
}

export function createCombinedCheckpointPatchArtifact(input: {
  run_root: string;
  run_id: string;
  checkpoint_refs: string[];
  source: string;
}): CombinedCheckpointPatchResult {
  const checkpointRefs = [...new Set(input.checkpoint_refs)];
  if (checkpointRefs.length === 0) {
    return failedCombinedPatch(input.run_root, checkpointRefs, "missing_verified_checkpoint");
  }

  const manifests: CheckpointManifest[] = [];
  for (const checkpointRef of checkpointRefs) {
    const validation = validateCheckpointManifest(input.run_root, checkpointRef);
    if (!validation.ok) return failedCombinedPatch(input.run_root, checkpointRefs, validation.reason ?? "checkpoint_manifest_missing");
    manifests.push(readCheckpointManifest(input.run_root, checkpointRef));
  }

  const temp = mkdtempSync(join(tmpdir(), "waygent-combined-patch-"));
  try {
    const clone = spawnSync("git", ["clone", "--quiet", "--shared", input.source, temp], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"]
    });
    if (clone.status !== 0) {
      return failedCombinedPatch(input.run_root, checkpointRefs, "patch_materialization_failed", {
        stdout: clone.stdout,
        stderr: clone.stderr
      });
    }

    for (const manifest of manifests) {
      if (!existsSync(manifest.worktree_path)) {
        return failedCombinedPatch(input.run_root, checkpointRefs, "checkpoint_worktree_missing", {
          checkpoint_ref: `${manifest.task_id}:${manifest.candidate_id}`,
          worktree_path: manifest.worktree_path
        });
      }
      for (const file of manifest.changed_files) {
        const from = join(manifest.worktree_path, file);
        const to = join(temp, file);
        if (existsSync(from)) {
          mkdirSync(dirname(to), { recursive: true });
          cpSync(from, to, { recursive: true, force: true });
        } else {
          rmSync(to, { recursive: true, force: true });
        }
      }
    }
    markUntrackedFilesForDiff(temp, manifests.flatMap((manifest) => manifest.changed_files));

    const diff = spawnSync("git", ["diff", "--binary"], {
      cwd: temp,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"]
    });
    if (diff.status !== 0) {
      return failedCombinedPatch(input.run_root, checkpointRefs, "patch_materialization_failed", {
        stdout: diff.stdout,
        stderr: diff.stderr
      });
    }

    const patchArtifact = writeArtifact(
      input.run_root,
      `checkpoints/apply/${input.run_id}.patch`,
      diff.stdout,
      "text/x-diff"
    );
    const patchPath = join(temp, ".waygent-combined-apply.patch");
    writeFileSync(patchPath, diff.stdout);
    const dryRun = spawnSync("git", ["apply", "--check", patchPath], {
      cwd: input.source,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"]
    });
    const status = dryRun.status === 0 ? "passed" : "failed";
    const evidenceArtifact = writeCombinedPatchEvidence(input.run_root, checkpointRefs, {
      status,
      patch_ref: patchArtifact.path,
      stdout: dryRun.stdout,
      stderr: dryRun.stderr
    });
    return {
      status,
      checkpoint_refs: checkpointRefs,
      patch_ref: patchArtifact.path,
      patch_sha256: patchArtifact.sha256,
      patch_byte_length: patchArtifact.byte_length,
      patch_artifact: patchArtifact,
      ...(status === "failed" ? { reason: "patch_dry_run_failed" as const } : {}),
      evidence_ref: evidenceArtifact.path,
      evidence_artifact: evidenceArtifact
    };
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
}

export function resolveRunArtifactPath(runRoot: string, ref: string): string {
  return isAbsolute(ref) ? ref : join(runRoot, ref);
}

function writeCheckpointDryRunEvidence(runRoot: string, checkpointRef: string, payload: Record<string, unknown>): ArtifactReference {
  const evidence = writeArtifact(
    runRoot,
    `checkpoints/dry-run-${Date.now()}-${Math.random().toString(16).slice(2)}.json`,
    `${JSON.stringify({ checkpoint_ref: checkpointRef, ...payload }, null, 2)}\n`
  );
  return evidence;
}

function failedCombinedPatch(
  runRoot: string,
  checkpointRefs: string[],
  reason: NonNullable<CombinedCheckpointPatchResult["reason"]>,
  payload: Record<string, unknown> = {}
): CombinedCheckpointPatchResult {
  const evidenceArtifact = writeCombinedPatchEvidence(runRoot, checkpointRefs, {
    status: "failed",
    reason,
    ...payload
  });
  return {
    status: "failed",
    checkpoint_refs: checkpointRefs,
    reason,
    evidence_ref: evidenceArtifact.path,
    evidence_artifact: evidenceArtifact
  };
}

function writeCombinedPatchEvidence(runRoot: string, checkpointRefs: string[], payload: Record<string, unknown>): ArtifactReference {
  const evidence = writeArtifact(
    runRoot,
    `checkpoints/apply-dry-run-${Date.now()}-${Math.random().toString(16).slice(2)}.json`,
    `${JSON.stringify({ checkpoint_refs: checkpointRefs, ...payload }, null, 2)}\n`
  );
  return evidence;
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
