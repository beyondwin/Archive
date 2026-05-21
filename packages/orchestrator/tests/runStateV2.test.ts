import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readRunStateV2, runStatePath, writeRunStateV2 } from "../src/runState";

describe("Waygent run state v2", () => {
  test("writes and reads v2 state without breaking v1 helpers", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-state-v2-"));
    writeRunStateV2(root, {
      schema: "waygent.run_state.v2",
      run_id: "run_v2",
      workspace: root,
      source_branch: "main",
      worktree_root: join(root, "worktrees"),
      run_root: join(root, "run_v2"),
      artifact_root: join(root, "run_v2", "artifacts"),
      state_path: runStatePath(root, "run_v2"),
      event_journal_path: join(root, "run_v2", "events.jsonl"),
      plan_path: null,
      spec_path: null,
      provider_profile: { provider: "fake", execution_mode: "multi-agent" },
      status: "initializing",
      lifecycle_outcome: null,
      current_phase: "preflight",
      tasks: {},
      safe_waves: [],
      provider_attempts: [],
      reviews: [],
      verification: [],
      recovery: [],
      apply: { status: "not_applied" },
      context: { snapshot_path: null, basis_hash: null },
      drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
      completion_audit: null,
      timestamps: {
        started_at: "2026-05-21T00:00:00Z",
        updated_at: "2026-05-21T00:00:00Z",
        completed_at: null
      }
    });

    expect(readRunStateV2(root, "run_v2")).toMatchObject({
      schema: "waygent.run_state.v2",
      status: "initializing"
    });
  });
});
