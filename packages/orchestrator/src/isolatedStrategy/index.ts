import { cpSync, existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { computeCacheKey } from "./cacheKey";
import { detectManifestDrift, enumerateWorkspaceManifest, type WorkspaceManifest } from "./workspaceManifest";
import {
  ensureRoot,
  evictLru,
  moveDirIntoSnapshot,
  readManifest,
  removeSnapshot,
  snapshotExists,
  snapshotPaths,
  writeManifest,
  SNAPSHOT_ROOT_REL
} from "./snapshot";

const DEFAULT_KEEP = Number(process.env.WAYGENT_VERIFY_SNAPSHOT_KEEP ?? "5");

export interface IsolatedStrategyEvidence {
  status: "prepared" | "failed";
  strategy: "isolated_workspace_resolve";
  isolation_status: "prepared" | "unavailable";
  isolated_packages: string[];
  resolved_paths: Record<string, string>;
  cache: { hit: boolean; key: string; snapshot_path: string | null };
  created_paths: string[];
  cleanup_status: "not_needed" | "pending" | "removed" | "failed";
  reason: string | null;
}

export interface PreparedIsolatedStrategy {
  evidence: IsolatedStrategyEvidence;
  cleanup(): void;
}

export function prepareIsolatedStrategy(input: {
  workspace: string;
  worktree: string;
}): PreparedIsolatedStrategy {
  const evidence: IsolatedStrategyEvidence = {
    status: "failed",
    strategy: "isolated_workspace_resolve",
    isolation_status: "unavailable",
    isolated_packages: [],
    resolved_paths: {},
    cache: { hit: false, key: "", snapshot_path: null },
    created_paths: [],
    cleanup_status: "not_needed",
    reason: null
  };

  let cacheKey: string;
  try {
    cacheKey = computeCacheKey({ workspace: input.workspace }).key;
  } catch (error) {
    evidence.reason = `isolation_unavailable.cache_key_io: ${describeError(error)}`;
    return { evidence, cleanup: () => {} };
  }
  evidence.cache.key = cacheKey;
  const paths = snapshotPaths(input.workspace, cacheKey);

  if (snapshotExists(paths)) {
    evidence.cache.hit = true;
  } else {
    evidence.cache.hit = false;
    try {
      buildSnapshot(input.workspace, paths);
    } catch (error) {
      removeSnapshot(paths);
      evidence.reason = `${normalizeFailureCode(error)}: ${describeError(error)}`;
      return { evidence, cleanup: () => {} };
    }
  }
  evidence.cache.snapshot_path = paths.dir;

  let snapshotManifest: WorkspaceManifest;
  try {
    snapshotManifest = readManifest(paths);
  } catch (error) {
    evidence.reason = `isolation_unavailable.snapshot_io: ${describeError(error)}`;
    return { evidence, cleanup: () => {} };
  }

  const currentManifest = enumerateWorkspaceManifest(input.worktree);
  const drift = detectManifestDrift(snapshotManifest, currentManifest);
  if (drift.drifted) {
    removeSnapshot(paths);
    const parts: string[] = [];
    if (drift.added.length > 0) parts.push(`${drift.added.join(",")} added`);
    if (drift.removed.length > 0) parts.push(`${drift.removed.join(",")} removed`);
    evidence.reason = `isolation_unavailable.manifest_drift: ${parts.join("; ")}`;
    return { evidence, cleanup: () => {} };
  }

  let resolvedPaths: Record<string, string>;
  try {
    resolvedPaths = materialize(input.worktree, paths, currentManifest);
    evidence.created_paths = ["node_modules"];
    evidence.cleanup_status = "pending";
  } catch (error) {
    cleanupWorktreeLinks(input.worktree);
    evidence.reason = `isolation_unavailable.materialize: ${describeError(error)}`;
    return { evidence, cleanup: () => {} };
  }

  evidence.status = "prepared";
  evidence.isolation_status = "prepared";
  evidence.isolated_packages = currentManifest.packages.map((p) => p.name).sort();
  evidence.resolved_paths = resolvedPaths;

  if (!evidence.cache.hit) {
    try {
      evictLru(paths.root, DEFAULT_KEEP);
    } catch {
      evidence.reason = `eviction_warning: failed_after_finalize`;
    }
  }

  return {
    evidence,
    cleanup() {
      if (evidence.cleanup_status !== "pending") return;
      try {
        cleanupWorktreeLinks(input.worktree);
        evidence.cleanup_status = "removed";
      } catch (error) {
        evidence.cleanup_status = "failed";
        evidence.reason = describeError(error);
      }
    }
  };
}

function buildSnapshot(workspace: string, paths: ReturnType<typeof snapshotPaths>): void {
  ensureRoot(paths);
  const staging = mkdtempSync(join(tmpdir(), "sp2-staging-"));
  try {
    cpSync(workspace, staging, { recursive: true, dereference: false });
    rmSync(join(staging, "node_modules"), { force: true, recursive: true });
    rmSync(join(staging, SNAPSHOT_ROOT_REL), { force: true, recursive: true });

    const installArgs = ["install"];
    if (process.env.WAYGENT_VERIFY_ISOLATION_FROZEN_LOCKFILE !== "0") {
      installArgs.push("--frozen-lockfile");
    }
    const result = spawnSync("bun", installArgs, {
      cwd: staging,
      encoding: "utf8",
      env: { ...process.env, BUN_INSTALL_VERBOSE: "0" }
    });
    if (result.status !== 0) {
      const tail = (result.stderr || "").slice(-2000);
      const err = new Error(`bun install failed: exit ${result.status}\n${tail}`);
      (err as Error & { code?: string }).code = "isolation_unavailable.bun_install";
      throw err;
    }

    moveDirIntoSnapshot(join(staging, "node_modules"), paths);
    writeManifest(paths, enumerateWorkspaceManifest(workspace));
  } finally {
    rmSync(staging, { force: true, recursive: true });
  }
}

function materialize(
  worktree: string,
  paths: ReturnType<typeof snapshotPaths>,
  currentManifest: WorkspaceManifest
): Record<string, string> {
  const target = join(worktree, "node_modules");
  if (existsSync(target)) {
    throw new Error("worktree_node_modules_exists");
  }
  cpSync(paths.nodeModules, target, { recursive: true, dereference: false });

  const resolved: Record<string, string> = {};
  for (const { name: pkgName, relative_path: relPath } of currentManifest.packages) {
    const linkPath = join(target, pkgName);
    rmSync(linkPath, { force: true, recursive: true });
    mkdirSync(join(linkPath, ".."), { recursive: true });
    const linkTarget = relative(join(linkPath, ".."), join(worktree, relPath));
    symlinkSync(linkTarget, linkPath, "dir");
    resolved[pkgName] = join(worktree, relPath);
  }
  return resolved;
}

function cleanupWorktreeLinks(worktree: string): void {
  const target = join(worktree, "node_modules");
  if (existsSync(target)) {
    rmSync(target, { force: true, recursive: true });
  }
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function normalizeFailureCode(error: unknown): string {
  if (error instanceof Error) {
    const code = (error as Error & { code?: string }).code;
    if (typeof code === "string" && code.startsWith("isolation_unavailable.")) return code;
  }
  return "isolation_unavailable.snapshot_io";
}
