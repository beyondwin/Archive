import { readdirSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";

export interface RepoMapEntry {
  path: string;
  extension: string;
  byte_size: number;
  symbols: string[];
}

const ignored = new Set(["node_modules", "target", ".git", "graphify-out", "dist", "build"]);

export function buildRepoMap(root: string, limit = 500): RepoMapEntry[] {
  const files = discoverFiles(root).slice(0, limit);
  return files.map((path) => {
    const absolute = join(root, path);
    return {
      path,
      extension: extname(path),
      byte_size: statSync(absolute).size,
      symbols: shallowSymbols(absolute)
    };
  });
}

export function discoverFiles(root: string): string[] {
  const rg = Bun.spawnSync(["rg", "--files"], { cwd: root, stdout: "pipe", stderr: "ignore" });
  if (rg.success) {
    return new TextDecoder().decode(rg.stdout).split("\n").filter((path) => path && !path.startsWith("graphify-out/")).sort();
  }
  const result: string[] = [];
  walk(root, root, result);
  return result.sort();
}

function walk(root: string, current: string, result: string[]): void {
  for (const item of readdirSync(current, { withFileTypes: true })) {
    if (ignored.has(item.name)) continue;
    const absolute = join(current, item.name);
    if (item.isDirectory()) walk(root, absolute, result);
    else result.push(relative(root, absolute));
  }
}

function shallowSymbols(path: string): string[] {
  if (!/\.(ts|tsx|rs)$/.test(path)) return [];
  const text = Bun.file(path).size < 100000 ? Bun.file(path).text() : Promise.resolve("");
  return [];
}
