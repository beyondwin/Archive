import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { cleanupStaleRunWorktree, deleteResolvedOrphan, markBlockedStaleRun, scanOrphanRuns } from "../src/orphanRuns";
import { readRunStateV2, writeRunStateV2 } from "../src/runState";

describe("orphan run advisory", () => {
  test("lists invalid run directories without deleting them", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-orphans-"));
    mkdirSync(join(root, "stale_run"), { recursive: true });

    const advisory = scanOrphanRuns({ root });

    expect(advisory.orphans).toEqual([expect.objectContaining({ id: "stale_run", kind: "run_dir" })]);
  });

  test("deletes exactly one validated orphan when confirmed", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-orphans-delete-"));
    mkdirSync(join(root, "stale_run"), { recursive: true });
    writeFileSync(join(root, "valid_state"), "not a run\n");
    const advisory = scanOrphanRuns({ root });

    const deleted = deleteResolvedOrphan({ root, id: "stale_run", yes: true, advisory });

    expect(deleted.deleted).toBe(true);
    expect(scanOrphanRuns({ root }).orphans.map((item) => item.id)).not.toContain("stale_run");
  });

  test("classifies stale running runs without treating recovered state as an orphan", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-stale-root-"));
    writeRunStateV2(root, fixtureState(root, "run_stale", {
      timestamps: {
        started_at: "2026-05-30T00:00:00.000Z",
        updated_at: "2026-05-30T00:00:00.000Z",
        completed_at: null
      }
    }));

    const advisory = scanOrphanRuns({
      root,
      stale: true,
      now: new Date("2026-05-30T01:00:01.000Z"),
      heartbeat_timeout_ms: 30 * 60 * 1000
    });

    expect(advisory.orphans).toEqual([]);
    expect(advisory.stale_runs).toEqual([
      expect.objectContaining({
        run_id: "run_stale",
        stale: true,
        reason: "heartbeat_expired",
        safe_actions: expect.arrayContaining(["inspect", "mark_blocked", "resume"])
      })
    ]);
  });

  test("marks a stale run blocked before cleaning only its Waygent worktree", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-stale-clean-root-"));
    const runId = "run_stale_clean";
    const worktreePath = join(root, "worktrees", `${runId}_task_a`);
    mkdirSync(worktreePath, { recursive: true });
    writeFileSync(join(worktreePath, "README.md"), "temporary worktree\n");
    writeRunStateV2(root, fixtureState(root, runId, {
      worktrees: [{
        task_id: "task_a",
        branch: "waygent/task_a",
        path: worktreePath,
        source: "worktree",
        source_commit: null,
        cleanup_status: "active"
      }],
      timestamps: {
        started_at: "2026-05-30T00:00:00.000Z",
        updated_at: "2026-05-30T00:00:00.000Z",
        completed_at: null
      }
    }));

    const marked = markBlockedStaleRun({
      root,
      id: runId,
      now: new Date("2026-05-30T01:00:01.000Z"),
      heartbeat_timeout_ms: 30 * 60 * 1000
    });
    expect(marked).toMatchObject({ run_id: runId, status: "blocked", reason: "heartbeat_expired" });

    const cleaned = cleanupStaleRunWorktree({ root, id: runId, now: new Date("2026-05-30T01:01:00.000Z") });

    expect(cleaned).toMatchObject({ run_id: runId, cleaned: true, removed_worktrees: [worktreePath] });
    expect(existsSync(worktreePath)).toBe(false);
    const state = readRunStateV2(root, runId);
    expect(state.status).toBe("blocked");
    expect(state.lifecycle_outcome).toBe("blocked");
    expect(state.worktrees?.[0]?.cleanup_status).toBe("removed");
  });
});

function fixtureState(root: string, runId: string, overrides: Partial<WaygentRunStateV2> = {}): WaygentRunStateV2 {
  const startedAt = "2026-05-30T00:00:00.000Z";
  const task = {
    id: "task_a",
    status: "running" as const,
    risk: "low" as const,
    dependencies: [],
    file_claims: [],
    attempts: [],
    task_packet_path: null,
    task_packet_sha256: null,
    unit_manifest: null,
    checkpoint_refs: [],
    latest_failure_class: null,
    decision_packet_ref: null,
    timing: {}
  };
  return {
    schema: "waygent.run_state.v2",
    run_id: runId,
    workspace: mkdtempSync(join(tmpdir(), "waygent-source-")),
    source_branch: null,
    worktree_root: join(root, "worktrees"),
    run_root: join(root, runId),
    artifact_root: join(root, runId, "artifacts"),
    state_path: join(root, runId, "state.json"),
    event_journal_path: join(root, runId, "events.jsonl"),
    plan_path: null,
    spec_path: null,
    provider_profile: {},
    status: "running",
    lifecycle_outcome: null,
    current_phase: "dispatch",
    worktrees: [],
    artifact_index: [],
    tasks: { task_a: task },
    safe_waves: [],
    provider_attempts: [],
    reviews: [],
    verification: [],
    recovery: [],
    apply: { status: "not_applied" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: null,
    timestamps: { started_at: startedAt, updated_at: startedAt, completed_at: null },
    ...overrides
  };
}
