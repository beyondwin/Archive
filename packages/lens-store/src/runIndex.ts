import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
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
