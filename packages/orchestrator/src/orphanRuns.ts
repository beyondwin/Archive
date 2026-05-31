import { existsSync, readdirSync, readFileSync, realpathSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, relative, resolve, join } from "node:path";
import type { StaleRunStatus, WaygentRunStateV2 } from "@waygent/contracts";
import { defaultRunRoot } from "./orchestrator";
import { readRunStateV2Result, writeRunStateV2 } from "./runState";

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
  stale_runs?: StaleRunStatus[];
}

export interface OrphanRunsScanInput {
  root?: string;
  auto_scan_legacy?: boolean;
  stale?: boolean;
  now?: Date;
  heartbeat_timeout_ms?: number;
}

export interface DeleteOrphanInput {
  root: string;
  id: string;
  yes: boolean;
  advisory?: OrphanRunAdvisory;
}

export interface MarkBlockedStaleRunInput {
  root: string;
  id: string;
  now?: Date;
  heartbeat_timeout_ms?: number;
}

export interface MarkBlockedStaleRunResult {
  run_id: string;
  status: "blocked";
  reason: StaleRunStatus["reason"];
  stale_run_status: StaleRunStatus;
}

export interface CleanupStaleRunWorktreeInput {
  root: string;
  id: string;
  now?: Date;
}

export interface CleanupStaleRunWorktreeResult {
  run_id: string;
  cleaned: boolean;
  removed_worktrees: string[];
  skipped_worktrees: Array<{ path: string; reason: string }>;
}

const DEFAULT_HEARTBEAT_TIMEOUT_MS = 30 * 60 * 1000;
const ACTIVE_RUN_STATUSES = new Set<WaygentRunStateV2["status"]>(["initializing", "running", "applying"]);
const BLOCKABLE_TASK_STATUSES = new Set<WaygentRunStateV2["tasks"][string]["status"]>([
  "pending",
  "ready",
  "running",
  "needs_fix",
  "review_required",
  "review_pending",
  "spec_review_running",
  "quality_review_running",
  "checkpoint_ready"
]);

function scanRoot(root: string, input: Pick<OrphanRunsScanInput, "stale" | "now" | "heartbeat_timeout_ms"> = {}): {
  orphans: OrphanRunEntry[];
  stale_runs: StaleRunStatus[];
} {
  const orphans: OrphanRunEntry[] = [];
  const staleRuns: StaleRunStatus[] = [];
  if (!existsSync(root)) return { orphans, stale_runs: staleRuns };
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
      } else if (input.stale) {
        const stateResult = readRunStateV2Result(root, entry.name);
        if (stateResult.status === "ok") {
          const status = classifyStaleRunState(stateResult.state, {
            now: input.now ?? new Date(),
            heartbeat_timeout_ms: input.heartbeat_timeout_ms ?? DEFAULT_HEARTBEAT_TIMEOUT_MS
          });
          if (status.stale) staleRuns.push(status);
        }
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
  return { orphans, stale_runs: staleRuns };
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
  const staleById = new Map<string, StaleRunStatus>();
  for (const { root, legacy } of rootsToScan) {
    const scanned = scanRoot(root, input);
    for (const entry of scanned.orphans) {
      const tagged: OrphanRunEntry = legacy
        ? { ...entry, migration_suggested: true }
        : entry;
      const existing = byId.get(tagged.id);
      if (!existing || existing.migration_suggested) byId.set(tagged.id, tagged);
    }
    for (const status of scanned.stale_runs) {
      if (!staleById.has(status.run_id)) staleById.set(status.run_id, status);
    }
  }
  const advisory: OrphanRunAdvisory = {
    root: explicit ? input.root! : "auto",
    checked_at: new Date().toISOString(),
    orphans: [...byId.values()]
  };
  if (input.stale) advisory.stale_runs = [...staleById.values()];
  return advisory;
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

export function classifyStaleRunState(state: WaygentRunStateV2, input: {
  now?: Date;
  heartbeat_timeout_ms?: number;
} = {}): StaleRunStatus {
  const now = input.now ?? new Date();
  const heartbeatTimeoutMs = input.heartbeat_timeout_ms ?? DEFAULT_HEARTBEAT_TIMEOUT_MS;

  if (state.lifecycle_outcome === "blocked" || (state.status === "blocked" && state.timestamps.completed_at)) {
    return staleStatus(state.run_id, true, "manual_pause");
  }
  if (!stateEventJournalMatches(state)) {
    return staleStatus(state.run_id, true, "state_event_mismatch");
  }
  if (!ACTIVE_RUN_STATUSES.has(state.status)) {
    return staleStatus(state.run_id, false, "active");
  }
  const activeWorktrees = (state.worktrees ?? []).filter((worktree) => worktree.cleanup_status === "active");
  const missingWorktree = activeWorktrees.find((worktree) => !existsSync(worktree.path));
  if (missingWorktree) {
    return staleStatus(state.run_id, true, "worktree_missing");
  }
  const runningAttempt = state.provider_attempts.find((attempt) => attempt.completed_at === null);
  if (runningAttempt && timestampExpired(runningAttempt.started_at, now, heartbeatTimeoutMs)) {
    return staleStatus(state.run_id, true, "provider_process_missing");
  }
  if (timestampExpired(state.timestamps.updated_at, now, heartbeatTimeoutMs)) {
    return staleStatus(state.run_id, true, "heartbeat_expired");
  }
  return staleStatus(state.run_id, false, "active");
}

export function markBlockedStaleRun(input: MarkBlockedStaleRunInput): MarkBlockedStaleRunResult {
  const stateResult = readRunStateV2Result(input.root, input.id);
  if (stateResult.status !== "ok") throw new Error(`run ${input.id} has ${stateResult.reason}`);
  const now = input.now ?? new Date();
  const stale = classifyStaleRunState(stateResult.state, {
    now,
    heartbeat_timeout_ms: input.heartbeat_timeout_ms ?? DEFAULT_HEARTBEAT_TIMEOUT_MS
  });
  if (!stale.stale) throw new Error(`run is not stale: ${input.id}`);
  const marked = staleStatus(input.id, true, stale.reason, ["inspect", "resume", "cleanup_worktree"]);
  const blockedAt = now.toISOString();
  const nextState: WaygentRunStateV2 = {
    ...stateResult.state,
    status: "blocked",
    lifecycle_outcome: "blocked",
    current_phase: "recover",
    stale_run_status: marked,
    tasks: Object.fromEntries(Object.entries(stateResult.state.tasks).map(([taskId, task]) => [
      taskId,
      BLOCKABLE_TASK_STATUSES.has(task.status)
        ? { ...task, status: "blocked", latest_failure_class: task.latest_failure_class ?? "stale_activity" }
        : task
    ])),
    recovery: [
      ...stateResult.state.recovery,
      {
        action: "mark_blocked",
        reason: stale.reason,
        recorded_at: blockedAt,
        stale_run_status: marked
      }
    ],
    timestamps: {
      ...stateResult.state.timestamps,
      updated_at: blockedAt,
      completed_at: stateResult.state.timestamps.completed_at ?? blockedAt
    }
  };
  writeRunStateV2(input.root, nextState);
  return {
    run_id: input.id,
    status: "blocked",
    reason: stale.reason,
    stale_run_status: marked
  };
}

export function cleanupStaleRunWorktree(input: CleanupStaleRunWorktreeInput): CleanupStaleRunWorktreeResult {
  const stateResult = readRunStateV2Result(input.root, input.id);
  if (stateResult.status !== "ok") throw new Error(`run ${input.id} has ${stateResult.reason}`);
  const state = stateResult.state;
  if (state.status !== "blocked" && state.lifecycle_outcome !== "blocked") {
    throw new Error(`run must be blocked before worktree cleanup: ${input.id}`);
  }

  const removed: string[] = [];
  const skipped: Array<{ path: string; reason: string }> = [];
  const nextWorktrees = (state.worktrees ?? []).map((worktree) => {
    if (worktree.cleanup_status !== "active") return worktree;
    if (!isSafeWorktreePath(state, worktree.path)) {
      skipped.push({ path: worktree.path, reason: "unsafe_worktree_path" });
      return worktree;
    }
    if (!existsSync(worktree.path)) {
      return { ...worktree, cleanup_status: "removed" as const };
    }
    if (!statSync(worktree.path).isDirectory()) {
      skipped.push({ path: worktree.path, reason: "not_a_directory" });
      return worktree;
    }
    rmSync(worktree.path, { recursive: true, force: false });
    removed.push(worktree.path);
    return { ...worktree, cleanup_status: "removed" as const };
  });
  const updatedAt = (input.now ?? new Date()).toISOString();
  const nextState: WaygentRunStateV2 = {
    ...state,
    worktrees: nextWorktrees,
    stale_run_status: staleStatus(state.run_id, true, "manual_pause", ["inspect", "resume", "cleanup_worktree"]),
    recovery: [
      ...state.recovery,
      {
        action: "cleanup_worktree",
        removed_worktrees: removed,
        skipped_worktrees: skipped,
        recorded_at: updatedAt
      }
    ],
    timestamps: { ...state.timestamps, updated_at: updatedAt }
  };
  writeRunStateV2(input.root, nextState);
  return {
    run_id: input.id,
    cleaned: removed.length > 0,
    removed_worktrees: removed,
    skipped_worktrees: skipped
  };
}

function staleStatus(
  runId: string,
  stale: boolean,
  reason: StaleRunStatus["reason"],
  safeActions?: StaleRunStatus["safe_actions"]
): StaleRunStatus {
  return {
    run_id: runId,
    stale,
    reason,
    safe_actions: safeActions ?? defaultSafeActions(stale, reason)
  };
}

function defaultSafeActions(stale: boolean, reason: StaleRunStatus["reason"]): StaleRunStatus["safe_actions"] {
  if (!stale) return ["inspect"];
  if (reason === "manual_pause") return ["inspect", "resume", "cleanup_worktree"];
  if (reason === "worktree_missing" || reason === "state_event_mismatch") return ["inspect", "mark_blocked"];
  return ["inspect", "mark_blocked", "resume"];
}

function timestampExpired(value: string | null | undefined, now: Date, timeoutMs: number): boolean {
  if (!value) return true;
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return true;
  return now.getTime() - parsed > timeoutMs;
}

function stateEventJournalMatches(state: WaygentRunStateV2): boolean {
  if (!state.event_journal_path || !existsSync(state.event_journal_path)) return true;
  try {
    const lines = readFileSync(state.event_journal_path, "utf8")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    for (const line of lines) {
      const event = JSON.parse(line) as { orchestrator_run_id?: unknown };
      if (typeof event.orchestrator_run_id === "string" && event.orchestrator_run_id !== state.run_id) return false;
    }
    return true;
  } catch {
    return false;
  }
}

function isSafeWorktreePath(state: WaygentRunStateV2, candidate: string): boolean {
  const worktreeRoot = safeRealpath(state.worktree_root);
  const worktreePath = safeRealpath(candidate);
  const workspacePath = safeRealpath(state.workspace);
  if (!isWithin(worktreeRoot, worktreePath)) return false;
  if (worktreePath === workspacePath || isWithin(workspacePath, worktreePath)) return false;
  return true;
}

function safeRealpath(path: string): string {
  try {
    return realpathSync(path);
  } catch {
    return resolve(path);
  }
}

function isWithin(parent: string, child: string): boolean {
  const rel = relative(parent, child);
  return rel === "" || (!rel.startsWith("..") && rel !== ".." && !isAbsolute(rel));
}
