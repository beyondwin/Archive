import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { appendEvent, runPaths } from "@waygent/lens-store";
import { createCheckpointArtifact, createCombinedCheckpointPatchArtifact, dryRunCheckpointPatch } from "../src/checkpointArtifacts";
import { applyRun, buildRunEvent, explainRun, inspectRun, resumeRun } from "../src/runCommands";
import { readRunStateV2, runStatePath, writeRunStateV2 } from "../src/runState";

describe("Waygent run commands v2", () => {
  const unsupportedSchema = ["waygent.run_state", "v1"].join(".");

  test("inspect and explain include execution explanation for v2 runs", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-inspect-explanation-"));
    const runId = "run_explain_v2";
    writeRunStateV2(root, {
      schema: "waygent.run_state.v2",
      run_id: runId,
      workspace: root,
      source_branch: "main",
      worktree_root: join(root, "worktrees"),
      run_root: join(root, runId),
      artifact_root: join(root, runId, "artifacts"),
      state_path: runStatePath(root, runId),
      event_journal_path: join(root, runId, "events.jsonl"),
      plan_path: null,
      spec_path: null,
      provider_profile: { provider: "fake" },
      status: "completed",
      lifecycle_outcome: "finished",
      current_phase: "complete",
      safe_waves: [
        {
          wave_id: "wave_1",
          ready: ["task_a"],
          concurrency: 1,
          timing: {
            started: "2026-05-22T00:00:00.000Z",
            completed: "2026-05-22T00:00:01.000Z",
            duration_ms: 1000
          },
          withheld: [{ task_id: "task_b", reason: "file_claim_conflict", detail: "same file" }]
        }
      ],
      tasks: {
        task_a: {
          id: "task_a",
          status: "verified",
          risk: "low",
          dependencies: [],
          file_claims: [{ path: "a.txt", mode: "owned" }],
          attempts: [],
          task_packet_path: null,
          task_packet_sha256: null,
          unit_manifest: null,
          checkpoint_refs: [],
          latest_failure_class: null,
          decision_packet_ref: null,
          timing: {}
        }
      },
      provider_attempts: [],
      reviews: [],
      verification: [],
      recovery: [],
      apply: { status: "not_applied" },
      context: { snapshot_path: null, basis_hash: null },
      drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
      completion_audit: null,
      timestamps: {
        started_at: "2026-05-22T00:00:00.000Z",
        updated_at: "2026-05-22T00:00:01.000Z",
        completed_at: "2026-05-22T00:00:01.000Z"
      }
    });
    appendEvent(join(root, runId, "events.jsonl"), buildRunEvent({
      run_id: runId,
      sequence: 1,
      event_type: "platform.run_started",
      phase: "platform",
      outcome: "running",
      summary: "Run opened.",
      payload: {}
    }));

    const inspected = inspectRun({ root, run: runId });
    expect(inspected.execution_explanation).toMatchObject({
      schema: "waygent.execution_explanation.v1",
      barriers: [{ task_id: "task_b", reason: "file_claim_conflict" }]
    });
    expect(explainRun({ root, run: runId }).summary).toContain("file_claim_conflict");
  });

  test("resume blocks runs without v2 state", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-commands-v2-"));
    const runId = "run_missing_state";
    const paths = runPaths(root, runId);
    appendEvent(paths.events, buildRunEvent({
      run_id: runId,
      sequence: 1,
      event_type: "platform.run_started",
      phase: "platform",
      outcome: "running",
      summary: "Run opened.",
      payload: {}
    }));

    expect(resumeRun({ root, run: runId, dry_run: true })).toEqual({
      run_id: runId,
      allowed_actions: ["inspect_run", "human_decision"],
      dry_run: true,
      blocked_by: "missing_run_state_v2"
    });
  });

  test("apply blocks unsupported state schema", async () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-workspace-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.name", "Test User"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "hello\n");
    Bun.spawnSync(["git", "add", "README.md"], { cwd: workspace });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });

    const root = mkdtempSync(join(tmpdir(), "waygent-run-commands-v2-"));
    const runId = "run_unsupported_state";
    mkdirSync(join(root, runId), { recursive: true });
    writeFileSync(join(root, runId, "state.json"), JSON.stringify({ schema: unsupportedSchema, run_id: runId }));

    await expect(applyRun({ root, run: runId, workspace })).resolves.toEqual({
      command: "apply",
      run_id: runId,
      status: "blocked",
      reason: "unsupported_run_state"
    });
  });

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
      allowed_actions: ["clean_source_checkout"],
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
    const worktree = mkdtempSync(join(tmpdir(), "waygent-apply-v2-worktree-"));
    Bun.spawnSync(["git", "clone", "--quiet", workspace, worktree]);
    writeFileSync(join(worktree, "README.md"), "after\n");
    const checkpoint = createCheckpointArtifact({
      run_root: runRoot,
      run_id: "run_apply",
      task_id: "task_apply",
      candidate_id: "candidate_task_apply",
      worktree_path: worktree,
      changed_files: ["README.md"],
      verification_refs: []
    });
    dryRunCheckpointPatch({ run_root: runRoot, checkpoint_ref: checkpoint.manifest_ref, source: workspace });
    const combined = createCombinedCheckpointPatchArtifact({
      run_root: runRoot,
      run_id: "run_apply",
      checkpoint_refs: [checkpoint.manifest_ref],
      source: workspace
    });
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
          checkpoint_refs: [checkpoint.manifest_ref],
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
      apply: { status: "not_applied", checkpoint_ref: checkpoint.manifest_ref },
      context: { snapshot_path: null, basis_hash: null },
      drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
      completion_audit: { status: "passed", combined_apply_evidence: combined },
      timestamps: {
        started_at: "2026-05-21T00:00:00Z",
        updated_at: "2026-05-21T00:00:00Z",
        completed_at: "2026-05-21T00:00:00Z"
      }
    });

    expect(resumeRun({ root, run: "run_apply", dry_run: true }).allowed_actions).toContain("apply_verified_checkpoint");
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
      completion_audit: {
        status: "passed",
        combined_apply_evidence: {
          status: "passed",
          checkpoint_refs: ["checkpoint_task_apply_candidate"],
          patch_ref: "artifacts/checkpoints/apply/run_missing.patch",
          patch_sha256: "a".repeat(64),
          patch_byte_length: 12,
          evidence_ref: "artifacts/checkpoints/apply-dry-run.json"
        }
      },
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
      reason: "checkpoint_manifest_missing"
    });
    expect(resumeRun({ root, run: "run_missing", dry_run: true }).allowed_actions).toEqual([
      "inspect_run",
      "retry_checkpoint_generation",
      "human_decision"
    ]);
  });

  test("apply reports missing checkpoint patches distinctly", async () => {
    const { root, workspace, checkpoint } = writeCompletedApplyRun("run_missing_patch");

    rmSync(join(root, "run_missing_patch", checkpoint.patch_ref), { force: true });

    expect(await applyRun({ root, run: "run_missing_patch", workspace })).toEqual({
      command: "apply",
      run_id: "run_missing_patch",
      status: "blocked",
      reason: "checkpoint_patch_missing"
    });
  });

  test("apply reports checkpoint digest mismatch distinctly", async () => {
    const { root, workspace, checkpoint } = writeCompletedApplyRun("run_digest_mismatch");

    writeFileSync(join(root, "run_digest_mismatch", checkpoint.patch_ref), "corrupted\n");

    expect(await applyRun({ root, run: "run_digest_mismatch", workspace })).toEqual({
      command: "apply",
      run_id: "run_digest_mismatch",
      status: "blocked",
      reason: "checkpoint_digest_mismatch"
    });
  });

  test("apply blocks completed v2 runs without a materialized final patch", async () => {
    const { root, workspace, combined } = writeCompletedApplyRun("run_missing_combined_patch");
    rmSync(join(root, "run_missing_combined_patch", combined!.patch_ref!), { force: true });

    expect(resumeRun({ root, run: "run_missing_combined_patch", dry_run: true }).allowed_actions).not.toContain(
      "apply_verified_checkpoint"
    );
    expect(await applyRun({ root, run: "run_missing_combined_patch", workspace })).toEqual({
      command: "apply",
      run_id: "run_missing_combined_patch",
      status: "blocked",
      reason: "checkpoint_patch_missing"
    });
  });

  test("resume does not allow apply when reconciliation drift blocks readiness", () => {
    const { root } = writeCompletedApplyRun("run_drifted");
    const state = readRunStateV2(root, "run_drifted");
    writeRunStateV2(root, {
      ...state,
      drift: {
        last_checked_at: "2026-05-21T00:00:00Z",
        records: [{ failure_class: "state_drift", severity: "blocking" }],
        unrepaired_blockers: [{ failure_class: "state_drift", severity: "blocking" }]
      }
    });

    expect(resumeRun({ root, run: "run_drifted", dry_run: true }).allowed_actions).not.toContain("apply_verified_checkpoint");
  });

  test("apply blocks when the readiness projection is not ready", async () => {
    const { root, workspace } = writeCompletedApplyRun("run_not_ready", { combined: false });

    expect(await applyRun({ root, run: "run_not_ready", workspace })).toEqual({
      command: "apply",
      run_id: "run_not_ready",
      status: "blocked",
      reason: "missing_apply_ready_evidence"
    });
  });

  test("apply verifies every final checkpoint even when the legacy apply ref is stale", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-apply-v2-root-"));
    const workspace = mkdtempSync(join(tmpdir(), "waygent-apply-v2-source-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "before\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });

    const runId = "run_stale_apply_ref";
    const runRoot = join(root, runId);
    const firstWorktree = mkdtempSync(join(tmpdir(), "waygent-apply-first-"));
    Bun.spawnSync(["git", "clone", "--quiet", workspace, firstWorktree]);
    writeFileSync(join(firstWorktree, "first.txt"), "first\n");
    const first = createCheckpointArtifact({
      run_root: runRoot,
      run_id: runId,
      task_id: "task_first",
      candidate_id: "candidate_task_first",
      worktree_path: firstWorktree,
      changed_files: ["first.txt"],
      verification_refs: []
    });
    dryRunCheckpointPatch({ run_root: runRoot, checkpoint_ref: first.manifest_ref, source: workspace });

    const secondWorktree = mkdtempSync(join(tmpdir(), "waygent-apply-second-"));
    Bun.spawnSync(["git", "clone", "--quiet", workspace, secondWorktree]);
    writeFileSync(join(secondWorktree, "second.txt"), "second\n");
    const second = createCheckpointArtifact({
      run_root: runRoot,
      run_id: runId,
      task_id: "task_second",
      candidate_id: "candidate_task_second",
      worktree_path: secondWorktree,
      changed_files: ["second.txt"],
      verification_refs: []
    });
    dryRunCheckpointPatch({ run_root: runRoot, checkpoint_ref: second.manifest_ref, source: workspace });
    const combined = createCombinedCheckpointPatchArtifact({
      run_root: runRoot,
      run_id: runId,
      checkpoint_refs: [first.manifest_ref, second.manifest_ref],
      source: workspace
    });
    writeRunStateV2(root, {
      schema: "waygent.run_state.v2",
      run_id: runId,
      workspace,
      source_branch: "main",
      worktree_root: join(root, "worktrees"),
      run_root: runRoot,
      artifact_root: join(runRoot, "artifacts"),
      state_path: runStatePath(root, runId),
      event_journal_path: join(runRoot, "events.jsonl"),
      plan_path: null,
      spec_path: null,
      provider_profile: { provider: "fake" },
      status: "completed",
      lifecycle_outcome: "finished",
      current_phase: "complete",
      tasks: {
        task_first: {
          id: "task_first",
          status: "verified",
          risk: "low",
          dependencies: [],
          file_claims: [{ path: "first.txt", mode: "owned" }],
          attempts: [],
          task_packet_path: null,
          task_packet_sha256: null,
          unit_manifest: { allowed_write_globs: ["first.txt"] },
          checkpoint_refs: [first.manifest_ref],
          latest_failure_class: null,
          decision_packet_ref: null,
          timing: {}
        },
        task_second: {
          id: "task_second",
          status: "verified",
          risk: "low",
          dependencies: [],
          file_claims: [{ path: "second.txt", mode: "owned" }],
          attempts: [],
          task_packet_path: null,
          task_packet_sha256: null,
          unit_manifest: { allowed_write_globs: ["second.txt"] },
          checkpoint_refs: [second.manifest_ref],
          latest_failure_class: null,
          decision_packet_ref: null,
          timing: {}
        }
      },
      safe_waves: [],
      provider_attempts: [],
      reviews: [],
      verification: [
        { task_id: "task_first", command: "test -f first.txt", status: "passed" },
        { task_id: "task_second", command: "test -f second.txt", status: "passed" }
      ],
      recovery: [],
      apply: { status: "not_applied", checkpoint_ref: first.manifest_ref },
      context: { snapshot_path: null, basis_hash: null },
      drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
      completion_audit: { status: "passed", combined_apply_evidence: combined },
      timestamps: {
        started_at: "2026-05-21T00:00:00Z",
        updated_at: "2026-05-21T00:00:00Z",
        completed_at: "2026-05-21T00:00:00Z"
      }
    });

    expect(await applyRun({ root, run: runId, workspace })).toMatchObject({
      command: "apply",
      run_id: runId,
      status: "applied"
    });
  });
});

function writeCompletedApplyRun(runId: string): {
  root: string;
  workspace: string;
  checkpoint: ReturnType<typeof createCheckpointArtifact>;
  combined: ReturnType<typeof createCombinedCheckpointPatchArtifact> | null;
}
function writeCompletedApplyRun(runId: string, options: { combined?: boolean } = {}): {
  root: string;
  workspace: string;
  checkpoint: ReturnType<typeof createCheckpointArtifact>;
  combined: ReturnType<typeof createCombinedCheckpointPatchArtifact> | null;
} {
  const root = mkdtempSync(join(tmpdir(), "waygent-apply-v2-root-"));
  const workspace = mkdtempSync(join(tmpdir(), "waygent-apply-v2-source-"));
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "before\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
  const runRoot = join(root, runId);
  const worktree = mkdtempSync(join(tmpdir(), "waygent-apply-v2-worktree-"));
  Bun.spawnSync(["git", "clone", "--quiet", workspace, worktree]);
  writeFileSync(join(worktree, "README.md"), "after\n");
  const checkpoint = createCheckpointArtifact({
    run_root: runRoot,
    run_id: runId,
    task_id: "task_apply",
    candidate_id: "candidate_task_apply",
    worktree_path: worktree,
    changed_files: ["README.md"],
    verification_refs: []
  });
  dryRunCheckpointPatch({ run_root: runRoot, checkpoint_ref: checkpoint.manifest_ref, source: workspace });
  const combined = options.combined === false
    ? null
    : createCombinedCheckpointPatchArtifact({
      run_root: runRoot,
      run_id: runId,
      checkpoint_refs: [checkpoint.manifest_ref],
      source: workspace
    });
  writeRunStateV2(root, {
    schema: "waygent.run_state.v2",
    run_id: runId,
    workspace,
    source_branch: "main",
    worktree_root: join(root, "worktrees"),
    run_root: runRoot,
    artifact_root: join(runRoot, "artifacts"),
    state_path: runStatePath(root, runId),
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
        checkpoint_refs: [checkpoint.manifest_ref],
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
    apply: { status: "not_applied", checkpoint_ref: checkpoint.manifest_ref },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: combined ? { status: "passed", combined_apply_evidence: combined } : { status: "passed" },
    timestamps: {
      started_at: "2026-05-21T00:00:00Z",
      updated_at: "2026-05-21T00:00:00Z",
      completed_at: "2026-05-21T00:00:00Z"
    }
  });

  return { root, workspace, checkpoint, combined };
}
