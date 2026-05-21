import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { applyRun, resumeRun } from "../src/runCommands";
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

  test("apply materializes v2 verified checkpoint patches", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-apply-v2-root-"));
    const workspace = mkdtempSync(join(tmpdir(), "waygent-apply-v2-source-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "before\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
    const runRoot = join(root, "run_apply");
    const patchPath = join(runRoot, "artifacts", "checkpoints", "task_apply.patch");
    mkdirSync(join(runRoot, "artifacts", "checkpoints"), { recursive: true });
    writeFileSync(patchPath, "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-before\n+after\n");
    writeRunStateV2(root, {
      schema: "waygent.run_state.v2",
      run_id: "run_apply",
      workspace,
      source_branch: "main",
      worktree_root: join(root, "worktrees"),
      run_root: runRoot,
      artifact_root: join(runRoot, "artifacts"),
      state_path: runStatePath(root, "run_apply"),
      event_journal_path: join(runRoot, "events.jsonl"),
      plan_path: null,
      spec_path: null,
      provider_profile: { provider: "fake" },
      status: "completed",
      lifecycle_outcome: "finished",
      current_phase: "complete",
      tasks: {
        task_apply: {
          id: "task_apply",
          status: "verified",
          risk: "low",
          dependencies: [],
          file_claims: [{ path: "README.md", mode: "owned" }],
          attempts: [],
          task_packet_path: null,
          task_packet_sha256: null,
          unit_manifest: { allowed_write_globs: ["README.md"] },
          checkpoint_refs: [patchPath],
          latest_failure_class: null,
          decision_packet_ref: null,
          timing: {}
        }
      },
      safe_waves: [],
      provider_attempts: [],
      reviews: [],
      verification: [{ task_id: "task_apply", command: "grep after README.md", status: "passed" }],
      recovery: [],
      apply: { status: "not_applied", checkpoint_ref: patchPath },
      context: { snapshot_path: null, basis_hash: null },
      drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
      completion_audit: { status: "passed" },
      timestamps: {
        started_at: "2026-05-21T00:00:00Z",
        updated_at: "2026-05-21T00:00:00Z",
        completed_at: "2026-05-21T00:00:00Z"
      }
    });

    expect(await applyRun({ root, run: "run_apply", workspace })).toMatchObject({
      command: "apply",
      run_id: "run_apply",
      status: "applied"
    });
  });

  test("apply blocks missing v2 checkpoint artifacts instead of throwing", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-apply-missing-root-"));
    const workspace = mkdtempSync(join(tmpdir(), "waygent-apply-missing-source-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "before\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
    const runRoot = join(root, "run_missing");
    writeRunStateV2(root, {
      schema: "waygent.run_state.v2",
      run_id: "run_missing",
      workspace,
      source_branch: "main",
      worktree_root: join(root, "worktrees"),
      run_root: runRoot,
      artifact_root: join(runRoot, "artifacts"),
      state_path: runStatePath(root, "run_missing"),
      event_journal_path: join(runRoot, "events.jsonl"),
      plan_path: null,
      spec_path: null,
      provider_profile: { provider: "fake" },
      status: "completed",
      lifecycle_outcome: "finished",
      current_phase: "complete",
      tasks: {
        task_apply: {
          id: "task_apply",
          status: "verified",
          risk: "low",
          dependencies: [],
          file_claims: [{ path: "README.md", mode: "owned" }],
          attempts: [],
          task_packet_path: null,
          task_packet_sha256: null,
          unit_manifest: { allowed_write_globs: ["README.md"] },
          checkpoint_refs: ["checkpoint_task_apply_candidate"],
          latest_failure_class: null,
          decision_packet_ref: null,
          timing: {}
        }
      },
      safe_waves: [],
      provider_attempts: [],
      reviews: [],
      verification: [{ task_id: "task_apply", command: "grep after README.md", status: "passed" }],
      recovery: [],
      apply: { status: "not_applied", checkpoint_ref: "checkpoint_task_apply_candidate" },
      context: { snapshot_path: null, basis_hash: null },
      drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
      completion_audit: { status: "passed" },
      timestamps: {
        started_at: "2026-05-21T00:00:00Z",
        updated_at: "2026-05-21T00:00:00Z",
        completed_at: "2026-05-21T00:00:00Z"
      }
    });

    expect(await applyRun({ root, run: "run_missing", workspace })).toEqual({
      command: "apply",
      run_id: "run_missing",
      status: "blocked",
      reason: "missing_verified_checkpoint"
    });
  });
});
