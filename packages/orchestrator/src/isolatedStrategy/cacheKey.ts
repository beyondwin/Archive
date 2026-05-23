import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT_PACKAGE_KEYS = ["dependencies", "workspaces"] as const;
const NUL = Buffer.from([0]);

export interface CacheKeyInput {
  workspace: string;
}

export interface CacheKeyComponent {
  path: string;
  sha256: string;
}

export interface CacheKeyResult {
  key: string;
  components: CacheKeyComponent[];
}

export function computeCacheKey(input: CacheKeyInput): CacheKeyResult {
  const { workspace } = input;
  const hash = createHash("sha256");
  const components: CacheKeyComponent[] = [];

  const lockfilePath = join(workspace, "bun.lock");
  const lockfileBytes = readFileSync(lockfilePath);
  hash.update(lockfileBytes);
  components.push({ path: "bun.lock", sha256: sha256Hex(lockfileBytes) });

  const manifests = collectPackageManifests(workspace);
  manifests.sort((a, b) =>
    a.relPath < b.relPath ? -1 : a.relPath > b.relPath ? 1 : 0
  );
  for (const entry of manifests) {
    hash.update(Buffer.from(entry.relPath, "utf8"));
    hash.update(NUL);
    hash.update(entry.contents);
    hash.update(NUL);
    components.push({ path: entry.relPath, sha256: sha256Hex(entry.contents) });
  }

  const rootPackagePath = join(workspace, "package.json");
  const rootRaw = readFileSync(rootPackagePath, "utf8");
  const rootObj = JSON.parse(rootRaw) as Record<string, unknown>;
  const filtered: Record<string, unknown> = {};
  for (const key of ROOT_PACKAGE_KEYS) {
    if (key in rootObj) filtered[key] = rootObj[key];
  }
  // Do not pass a replacer array here: JSON.stringify applies it to every
  // nested object, which would strip the actual dependency keys inside.
  const canonical = JSON.stringify(filtered, null, 0);
  const canonicalBytes = Buffer.from(canonical, "utf8");
  hash.update(canonicalBytes);
  components.push({ path: "package.json#canonical", sha256: sha256Hex(canonicalBytes) });

  return { key: `sha256:${hash.digest("hex")}`, components };
}

function collectPackageManifests(
  workspace: string
): { relPath: string; contents: Buffer }[] {
  const packagesDir = join(workspace, "packages");
  let entries: string[];
  try {
    entries = readdirSync(packagesDir);
  } catch {
    return [];
  }
  const results: { relPath: string; contents: Buffer }[] = [];
  for (const name of entries) {
    const manifestPath = join(packagesDir, name, "package.json");
    let isFile = false;
    try {
      isFile = statSync(manifestPath).isFile();
    } catch {
      isFile = false;
    }
    if (!isFile) continue;
    const contents = readFileSync(manifestPath);
    results.push({ relPath: `packages/${name}/package.json`, contents });
  }
  return results;
}

function sha256Hex(input: Buffer): string {
  return createHash("sha256").update(input).digest("hex");
}
