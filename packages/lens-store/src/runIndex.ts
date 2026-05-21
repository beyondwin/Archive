import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export function writeLatestRunId(root: string, runId: string): void {
  mkdirSync(root, { recursive: true });
  writeFileSync(join(root, "latest"), `${runId}\n`);
}

export function readLatestRunId(root: string): string | null {
  try {
    const value = readFileSync(join(root, "latest"), "utf8").trim();
    return value.length > 0 ? value : null;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

export function listRunIds(root: string): string[] {
  try {
    return readdirSync(root, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .filter((runId) => existsSync(join(root, runId, "events.jsonl")))
      .sort();
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}
