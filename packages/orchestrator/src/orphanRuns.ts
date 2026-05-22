import { existsSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";

export interface OrphanRunEntry {
  id: string;
  kind: "run_dir" | "worktree";
  path: string;
  reason: string;
}

export interface OrphanRunAdvisory {
  root: string;
  checked_at: string;
  orphans: OrphanRunEntry[];
}

export interface DeleteOrphanInput {
  root: string;
  id: string;
  yes: boolean;
  advisory?: OrphanRunAdvisory;
}

export function scanOrphanRuns(input: { root: string }): OrphanRunAdvisory {
  const orphans: OrphanRunEntry[] = [];
  if (!existsSync(input.root)) return { root: input.root, checked_at: new Date().toISOString(), orphans };
  for (const entry of readdirSync(input.root, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name === "worktrees") continue;
    const runRoot = join(input.root, entry.name);
    const statePath = join(runRoot, "state.json");
    if (!existsSync(statePath)) {
      orphans.push({ id: entry.name, kind: "run_dir", path: runRoot, reason: "missing_state_json" });
      continue;
    }
    try {
      const parsed = JSON.parse(readFileSync(statePath, "utf8")) as { schema?: unknown; run_id?: unknown };
      if (parsed.schema !== "waygent.run_state.v2" || parsed.run_id !== entry.name) {
        orphans.push({ id: entry.name, kind: "run_dir", path: runRoot, reason: "invalid_state_json" });
      }
    } catch {
      orphans.push({ id: entry.name, kind: "run_dir", path: runRoot, reason: "unreadable_state_json" });
    }
  }
  const worktreeRoot = join(input.root, "worktrees");
  if (existsSync(worktreeRoot)) {
    for (const entry of readdirSync(worktreeRoot, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const runId = entry.name.split("_task_")[0] ?? entry.name;
      if (!existsSync(join(input.root, runId, "state.json"))) {
        orphans.push({ id: entry.name, kind: "worktree", path: join(worktreeRoot, entry.name), reason: "missing_corresponding_run_state" });
      }
    }
  }
  return { root: input.root, checked_at: new Date().toISOString(), orphans };
}

export function deleteResolvedOrphan(input: DeleteOrphanInput): { deleted: boolean; id: string; path: string; reason: string } {
  if (!input.yes) throw new Error("orphan deletion requires --yes");
  if (input.id === "--delete-all" || input.id === "all") throw new Error("delete-all is not supported; delete exactly one orphan id");
  const advisory = input.advisory ?? scanOrphanRuns({ root: input.root });
  const matches = advisory.orphans.filter((orphan) => orphan.id === input.id);
  if (matches.length !== 1) throw new Error(`orphan id must resolve to exactly one entry: ${input.id}`);
  const orphan = matches[0]!;
  if (!existsSync(orphan.path) || !statSync(orphan.path).isDirectory()) throw new Error(`orphan path is not a directory: ${orphan.path}`);
  rmSync(orphan.path, { recursive: true, force: false });
  return { deleted: true, id: orphan.id, path: orphan.path, reason: orphan.reason };
}
