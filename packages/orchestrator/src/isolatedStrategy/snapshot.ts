import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync
} from "node:fs";
import { join } from "node:path";
import type { WorkspaceManifest } from "./workspaceManifest";

export const SNAPSHOT_ROOT_REL = ".waygent/verify-env-snapshot";

export interface SnapshotPaths {
  root: string;
  dir: string;
  nodeModules: string;
  manifestFile: string;
}

export function snapshotPaths(workspace: string, cacheKey: string): SnapshotPaths {
  const root = join(workspace, SNAPSHOT_ROOT_REL);
  const dir = join(root, cacheKey);
  return {
    root,
    dir,
    nodeModules: join(dir, "node_modules"),
    manifestFile: join(dir, "manifest.json")
  };
}

export function snapshotExists(paths: SnapshotPaths): boolean {
  return existsSync(paths.nodeModules) && existsSync(paths.manifestFile);
}

export function ensureRoot(paths: SnapshotPaths): void {
  mkdirSync(paths.root, { recursive: true });
}

export function writeManifest(paths: SnapshotPaths, manifest: WorkspaceManifest): void {
  // Do not pass a replacer array here: JSON.stringify applies it to every
  // nested object and would strip the package entry fields.
  writeFileSync(paths.manifestFile, JSON.stringify(manifest, null, 2));
}

export function readManifest(paths: SnapshotPaths): WorkspaceManifest {
  return JSON.parse(readFileSync(paths.manifestFile, "utf8")) as WorkspaceManifest;
}

export function moveDirIntoSnapshot(src: string, paths: SnapshotPaths): void {
  mkdirSync(paths.dir, { recursive: true });
  cpSync(src, paths.nodeModules, { recursive: true, dereference: false });
  rmSync(src, { force: true, recursive: true });
}

export function removeSnapshot(paths: SnapshotPaths): void {
  rmSync(paths.dir, { force: true, recursive: true });
}

export function evictLru(rootPath: string, keep: number): void {
  if (!existsSync(rootPath)) return;
  const entries = readdirSync(rootPath)
    .map((name) => {
      const full = join(rootPath, name);
      try {
        return { name, full, mtimeMs: statSync(full).mtimeMs };
      } catch {
        return null;
      }
    })
    .filter((e): e is { name: string; full: string; mtimeMs: number } => e !== null)
    .sort((a, b) => a.mtimeMs - b.mtimeMs);

  const removeCount = Math.max(0, entries.length - keep);
  for (let i = 0; i < removeCount; i++) {
    const entry = entries[i];
    if (entry) rmSync(entry.full, { force: true, recursive: true });
  }
}
