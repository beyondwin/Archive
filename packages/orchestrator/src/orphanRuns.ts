import { existsSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defaultRunRoot } from "./orchestrator";

export interface OrphanRunEntry {
  id: string;
  kind: "run_dir" | "worktree";
  path: string;
  reason: string;
  migration_suggested?: boolean;
}

export interface OrphanRunAdvisory {
  root: string;
  checked_at: string;
  orphans: OrphanRunEntry[];
}

export interface OrphanRunsScanInput {
  root?: string;
  auto_scan_legacy?: boolean;
}

export interface DeleteOrphanInput {
  root: string;
  id: string;
  yes: boolean;
  advisory?: OrphanRunAdvisory;
}

function scanRoot(root: string): OrphanRunEntry[] {
  const orphans: OrphanRunEntry[] = [];
  if (!existsSync(root)) return orphans;
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name === "worktrees") continue;
    const runRoot = join(root, entry.name);
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
  const worktreeRoot = join(root, "worktrees");
  if (existsSync(worktreeRoot)) {
    for (const entry of readdirSync(worktreeRoot, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const runId = entry.name.split("_task_")[0] ?? entry.name;
      if (!existsSync(join(root, runId, "state.json"))) {
        orphans.push({ id: entry.name, kind: "worktree", path: join(worktreeRoot, entry.name), reason: "missing_corresponding_run_state" });
      }
    }
  }
  return orphans;
}

export function scanOrphanRuns(input: OrphanRunsScanInput = {}): OrphanRunAdvisory {
  const explicit = typeof input.root === "string";
  const autoLegacy = input.auto_scan_legacy !== false;
  const rootsToScan = explicit
    ? [{ root: input.root!, legacy: false }]
    : [
        { root: defaultRunRoot(), legacy: false },
        ...(autoLegacy ? [{ root: join(tmpdir(), "waygent-runs"), legacy: true }] : [])
      ];

  const byId = new Map<string, OrphanRunEntry>();
  for (const { root, legacy } of rootsToScan) {
    for (const entry of scanRoot(root)) {
      const tagged: OrphanRunEntry = legacy
        ? { ...entry, migration_suggested: true }
        : entry;
      const existing = byId.get(tagged.id);
      if (!existing || existing.migration_suggested) byId.set(tagged.id, tagged);
    }
  }
  return {
    root: explicit ? input.root! : "auto",
    checked_at: new Date().toISOString(),
    orphans: [...byId.values()]
  };
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
