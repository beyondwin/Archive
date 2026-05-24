import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { appendEvent, writeArtifact } from "@waygent/lens-store";
import {
  createCheckpointArtifact,
  createCombinedCheckpointPatchArtifact,
  dryRunCheckpointPatch,
  readCheckpointManifest,
  resolveRunArtifactPath
} from "../src/checkpointArtifacts";
import { buildRunEvent } from "../src/runEvents";
import { readRunStateV2, runStatePath, writeRunStateV2 } from "../src/runState";
import { reconcileRunState } from "../src/stateReconciliation";

describe("Waygent state reconciliation", () => {
  test("passes a completed run with provider, verification, checkpoint, combined patch, and terminal event evidence", () => {
    const fixture = writeReconciliationFixture("run_reconcile_ok");

    const report = reconcileRunState(fixture.root, fixture.runId);

    expect(report.passed).toBe(true);
    expect(report.unrepaired_blockers).toEqual([]);
    expect(readRunStateV2(fixture.root, fixture.runId).drift.unrepaired_blockers).toEqual([]);
  });

  test.each([
    ["missing_provider_stdout", "artifact_missing"],
    ["missing_worker_result", "artifact_missing"],
    ["missing_kernel_result", "artifact_missing"],
    ["missing_checkpoint_manifest", "artifact_missing"],
    ["missing_checkpoint_patch", "artifact_missing"],
    ["checkpoint_digest_mismatch", "state_drift"],
    ["missing_checkpoint_dry_run_evidence", "artifact_missing"],
    ["missing_combined_patch", "artifact_missing"],
    ["combined_patch_digest_mismatch", "state_drift"],
    ["missing_event_journal", "artifact_missing"],
    ["completed_without_terminal_trust_event", "state_drift"],
    ["completed_with_failed_completion_audit", "state_drift"]
  ] as const)("blocks %s as %s", (mutation, expectedType) => {
    const fixture = writeReconciliationFixture(`run_${mutation}`);
    mutateFixture(fixture, mutation);

    const report = reconcileRunState(fixture.root, fixture.runId);
    const state = readRunStateV2(fixture.root, fixture.runId);

    expect(report.passed).toBe(false);
    expect(report.unrepaired_blockers[0]).toMatchObject({
      type: expectedType,
      severity: "blocking",
      failure_class: expectedType
    });
    expect(state.drift.unrepaired_blockers.length).toBeGreaterThan(0);
  });

  test("blocks when indexed artifact digest drifts from bytes", () => {
    const fixture = writeReconciliationFixture("run_index_drift");
    const state = readRunStateV2(fixture.root, fixture.runId);
    const indexedRef = state.provider_attempts[0]!.stdout_ref;
    writeRunStateV2(fixture.root, {
      ...state,
      artifact_index: [
        {
          ref: indexedRef,
          media_type: "text/plain",
          sha256: "a".repeat(64),
          byte_length: 12,
          producer_phase: "provider",
          task_id: "task_a",
          created_at: "2026-05-22T00:00:00.000Z"
        }
      ]
    });

    const report = reconcileRunState(fixture.root, fixture.runId);

    expect(report.passed).toBe(false);
    expect(report.records).toContainEqual(expect.objectContaining({
      failure_class: "state_drift",
      artifact_ref: indexedRef
    }));
  });
});

type ReconciliationMutation =
  | "missing_provider_stdout"
  | "missing_worker_result"
  | "missing_kernel_result"
  | "missing_checkpoint_manifest"
  | "missing_checkpoint_patch"
  | "checkpoint_digest_mismatch"
  | "missing_checkpoint_dry_run_evidence"
  | "missing_combined_patch"
  | "combined_patch_digest_mismatch"
  | "missing_event_journal"
  | "completed_without_terminal_trust_event"
  | "completed_with_failed_completion_audit";

interface ReconciliationFixture {
  root: string;
  runId: string;
  runRoot: string;
  workspace: string;
  state: WaygentRunStateV2;
}

function writeReconciliationFixture(runId: string): ReconciliationFixture {
  const root = mkdtempSync(join(tmpdir(), "waygent-reconcile-root-"));
  const workspace = mkdtempSync(join(tmpdir(), "waygent-reconcile-source-"));
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "before\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });

  const runRoot = join(root, runId);
  const worktree = mkdtempSync(join(tmpdir(), "waygent-reconcile-worktree-"));
  Bun.spawnSync(["git", "clone", "--quiet", workspace, worktree]);
  writeFileSync(join(worktree, "README.md"), "after\n");

  const taskPacket = writeArtifact(runRoot, "task_packets/task_a.json", JSON.stringify({ task_id: "task_a" }));
  const stdin = writeArtifact(runRoot, "provider/attempt_task_a_1.stdin.txt", "prompt", "text/plain");
  const stdout = writeArtifact(runRoot, "provider/attempt_task_a_1.stdout.txt", "{\"status\":\"completed\"}", "text/plain");
  const stderr = writeArtifact(runRoot, "provider/attempt_task_a_1.stderr.txt", "", "text/plain");
  const worker = writeArtifact(runRoot, "worker/task_a.json", JSON.stringify({ status: "completed" }));
  const kernel = writeArtifact(runRoot, "kernel/verify_task_a.json", JSON.stringify({ exit_code: 0 }));
  const checkpoint = createCheckpointArtifact({
    run_root: runRoot,
    run_id: runId,
    task_id: "task_a",
    candidate_id: "candidate_task_a",
    worktree_path: worktree,
    changed_files: ["README.md"],
    verification_refs: [kernel.path]
  });
  dryRunCheckpointPatch({ run_root: runRoot, checkpoint_ref: checkpoint.manifest_ref, source: workspace });
  const combined = createCombinedCheckpointPatchArtifact({
    run_root: runRoot,
    run_id: runId,
    checkpoint_refs: [checkpoint.manifest_ref],
    source: workspace
  });

  const state: WaygentRunStateV2 = {
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
      task_a: {
        id: "task_a",
        status: "verified",
        risk: "low",
        dependencies: [],
        file_claims: [{ path: "README.md", mode: "owned" }],
        attempts: ["attempt_task_a_1"],
        task_packet_path: join(runRoot, taskPacket.path),
        task_packet_sha256: taskPacket.sha256,
        unit_manifest: { allowed_write_globs: ["README.md"], forbidden_write_globs: [".git/**"] },
        checkpoint_refs: [checkpoint.manifest_ref],
        latest_failure_class: null,
        decision_packet_ref: null,
        timing: {}
      }
    },
    safe_waves: [],
    provider_attempts: [{
      schema: "runway.provider_attempt.v1",
      attempt_id: "attempt_task_a_1",
      run_id: runId,
      task_id: "task_a",
      role: "implement",
      provider: "fake",
      command: ["fake-provider"],
      cwd: worktree,
      stdin_ref: stdin.path,
      stdout_ref: stdout.path,
      stderr_ref: stderr.path,
      event_stream_ref: null,
      exit_code: 0,
      timed_out: false,
      started_at: "2026-05-21T00:00:00Z",
      completed_at: "2026-05-21T00:00:01Z",
      worker_result_ref: worker.path,
      failure_class: null
    }],
    reviews: [],
    verification: [{
      verification_id: "verify_task_a",
      task_id: "task_a",
      command: "grep after README.md",
      cwd: worktree,
      kernel_result_ref: kernel.path,
      status: "passed"
    }],
    recovery: [],
    apply: { status: "not_applied", checkpoint_ref: checkpoint.manifest_ref },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: {
      status: "passed",
      combined_apply_evidence: combined,
      state_reconciliation: { passed: true, records: [], unrepaired_blockers: [] },
      residual_risk: []
    },
    timestamps: {
      started_at: "2026-05-21T00:00:00Z",
      updated_at: "2026-05-21T00:00:01Z",
      completed_at: "2026-05-21T00:00:01Z"
    }
  };
  writeRunStateV2(root, state);
  appendEvent(state.event_journal_path, buildRunEvent({
    run_id: runId,
    sequence: 1,
    event_type: "lens.trust_report_updated",
    phase: "lens",
    outcome: "success",
    summary: "Trust report updated.",
    payload: { trust_status: "trusted" }
  }));
  return { root, runId, runRoot, workspace, state };
}

function mutateFixture(fixture: ReconciliationFixture, mutation: ReconciliationMutation): void {
  const state = readRunStateV2(fixture.root, fixture.runId);
  const attempt = state.provider_attempts[0]!;
  const verification = state.verification[0] as { kernel_result_ref: string };
  const checkpointRef = state.tasks.task_a!.checkpoint_refs[0]!;
  const manifest = readCheckpointManifest(fixture.runRoot, checkpointRef);
  const combined = state.completion_audit?.combined_apply_evidence as {
    patch_ref?: string;
    evidence_ref?: string;
  };

  switch (mutation) {
    case "missing_provider_stdout":
      removeArtifact(fixture.runRoot, attempt.stdout_ref);
      break;
    case "missing_worker_result":
      removeArtifact(fixture.runRoot, attempt.worker_result_ref!);
      break;
    case "missing_kernel_result":
      removeArtifact(fixture.runRoot, verification.kernel_result_ref);
      break;
    case "missing_checkpoint_manifest":
      removeArtifact(fixture.runRoot, checkpointRef);
      break;
    case "missing_checkpoint_patch":
      removeArtifact(fixture.runRoot, manifest.patch_ref);
      break;
    case "checkpoint_digest_mismatch":
      writeFileSync(resolveRunArtifactPath(fixture.runRoot, manifest.patch_ref), "corrupt\n");
      break;
    case "missing_checkpoint_dry_run_evidence":
      removeArtifact(fixture.runRoot, manifest.dry_run_evidence_ref!);
      break;
    case "missing_combined_patch":
      removeArtifact(fixture.runRoot, combined.patch_ref!);
      break;
    case "combined_patch_digest_mismatch":
      writeFileSync(resolveRunArtifactPath(fixture.runRoot, combined.patch_ref!), "corrupt\n");
      break;
    case "missing_event_journal":
      rmSync(state.event_journal_path, { force: true });
      break;
    case "completed_without_terminal_trust_event":
      mkdirSync(fixture.runRoot, { recursive: true });
      writeFileSync(state.event_journal_path, "");
      break;
    case "completed_with_failed_completion_audit":
      writeRunStateV2(fixture.root, {
        ...state,
        completion_audit: {
          ...(state.completion_audit ?? {}),
          status: "failed",
          residual_risk: ["state_reconciliation:blocking"]
        }
      });
      break;
  }
}

function removeArtifact(runRoot: string, ref: string): void {
  rmSync(resolveRunArtifactPath(runRoot, ref), { force: true });
}
