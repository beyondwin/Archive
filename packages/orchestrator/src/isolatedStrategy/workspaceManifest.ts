import { readFileSync, readdirSync, type Dirent } from "node:fs";
import { join } from "node:path";

export interface WorkspacePackage {
  name: string;
  relative_path: string;
}

export interface WorkspaceManifest {
  packages: WorkspacePackage[];
}

export interface ManifestDrift {
  drifted: boolean;
  added: string[];
  removed: string[];
}

const WAYGENT_SCOPE_PREFIX = "@waygent/";

export function enumerateWorkspaceManifest(workspaceRoot: string): WorkspaceManifest {
  const packagesDir = join(workspaceRoot, "packages");
  const entries = safeReadDir(packagesDir);
  const packages: WorkspacePackage[] = [];

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const relativePath = `packages/${entry.name}`;
    const manifestPath = join(packagesDir, entry.name, "package.json");
    const raw = safeRead(manifestPath);
    if (raw === null) continue;
    const parsed = safeParseJson(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) continue;
    const nameValue = (parsed as { name?: unknown }).name;
    if (typeof nameValue !== "string" || !nameValue.startsWith(WAYGENT_SCOPE_PREFIX)) continue;
    packages.push({ name: nameValue, relative_path: relativePath });
  }

  packages.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return { packages };
}

export function detectManifestDrift(
  snapshot: WorkspaceManifest,
  current: WorkspaceManifest
): ManifestDrift {
  const snapshotNames = new Set(snapshot.packages.map((p) => p.name));
  const currentNames = new Set(current.packages.map((p) => p.name));

  const added: string[] = [];
  for (const name of currentNames) {
    if (!snapshotNames.has(name)) added.push(name);
  }
  const removed: string[] = [];
  for (const name of snapshotNames) {
    if (!currentNames.has(name)) removed.push(name);
  }
  added.sort();
  removed.sort();

  return { drifted: added.length > 0 || removed.length > 0, added, removed };
}

function safeReadDir(path: string): Dirent[] {
  try {
    return readdirSync(path, { withFileTypes: true, encoding: "utf8" }) as Dirent[];
  } catch {
    return [];
  }
}

function safeRead(path: string): string | null {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

function safeParseJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
