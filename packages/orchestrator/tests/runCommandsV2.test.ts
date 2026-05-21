import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { resumeRun } from "../src/runCommands";
import { runStatePath, writeRunStateV2 } from "../src/runState";

describe("Waygent run commands v2", () => {
  test("resume exposes blocked v2 decision state without guessing", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-commands-v2-"));
    writeRunStateV2(root, {
      schema: "waygent.run_state.v2",
      run_id: "run_blocked",
      workspace: root,
      source_branch: "main",
      worktree_root: join(root, "worktrees"),
      run_root: join(root, "run_blocked"),
      artifact_root: join(root, "run_blocked", "artifacts"),
      state_path: runStatePath(root, "run_blocked"),
      event_journal_path: join(root, "run_blocked", "events.jsonl"),
      plan_path: null,
      spec_path: null,
      provider_profile: { provider: "fake" },
      status: "blocked",
      lifecycle_outcome: "blocked",
      current_phase: "recover",
      tasks: {
        task_blocked: {
          id: "task_blocked",
          status: "blocked",
          risk: "low",
          dependencies: [],
          file_claims: [{ path: "README.md", mode: "owned" }],
          attempts: [],
          task_packet_path: null,
          task_packet_sha256: null,
          unit_manifest: { allowed_write_globs: ["README.md"] },
          checkpoint_refs: [],
          latest_failure_class: "dirty_source_checkout",
          decision_packet_ref: "artifacts/decisions/task_blocked.json",
          timing: {}
        }
      },
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

    expect(await resumeRun({ root, run: "run_blocked", dry_run: true })).toMatchObject({
      run_id: "run_blocked",
      allowed_actions: ["human_decision"],
      dry_run: true
    });
  });
});
