import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { writeArtifact } from "@waygent/lens-store";
import {
  createCheckpointArtifact,
  createCombinedCheckpointPatchArtifact,
  dryRunCheckpointPatch,
  resolveRunArtifactPath
} from "../src/checkpointArtifacts";
import { runStatePath } from "../src/runState";
import { evaluateTerminalCompletionInvariant } from "../src/terminalInvariant";

describe("terminal completion invariant", () => {
  test("passes only when completion audit, checkpoints, combined apply, and reconciliation are apply-ready", () => {
    const fixture = writeTerminalFixture("run_terminal_ok");

    expect(evaluateTerminalCompletionInvariant(fixture.state)).toEqual({
      passed: true,
      blockers: []
    });
  });

  test("rejects completed state paired with a failed completion audit", () => {
    const fixture = writeTerminalFixture("run_terminal_failed_audit");
    fixture.state.status = "completed";
    fixture.state.lifecycle_outcome = "finished";
    fixture.state.completion_audit = {
      ...fixture.state.completion_audit,
      status: "failed",
      residual_risk: ["state_reconciliation:blocking"]
    };

    const report = evaluateTerminalCompletionInvariant(fixture.state);

    expect(report.passed).toBe(false);
    expect(report.blockers).toEqual(expect.arrayContaining([
      expect.objectContaining({ code: "completed_with_failed_completion_audit" }),
      expect.objectContaining({ code: "completion_audit_not_passed" })
    ]));
  });

  test("requires review evidence for high-risk multi-agent tasks", () => {
    const fixture = writeTerminalFixture("run_terminal_review_required");
    fixture.state.tasks.task_a!.risk = "high";

    expect(evaluateTerminalCompletionInvariant(fixture.state).blockers).toContainEqual(
      expect.objectContaining({ code: "review_evidence_missing", task_id: "task_a" })
    );

    fixture.state.completion_audit = {
      ...fixture.state.completion_audit,
      review_evidence: [{ task_id: "task_a", status: "passed" }]
    };

    expect(evaluateTerminalCompletionInvariant(fixture.state)).toEqual({
      passed: true,
      blockers: []
    });
  });

  test("requires method evidence or an allowlisted waiver when the run enables the method gate", () => {
    const fixture = writeTerminalFixture("run_terminal_method_required");
    fixture.state.method_evidence_required = true;

    expect(evaluateTerminalCompletionInvariant(fixture.state).blockers).toContainEqual(
      expect.objectContaining({ code: "method_evidence_missing", task_id: "task_a" })
    );

    writeFileSync(resolveRunArtifactPath(fixture.runRoot, fixture.workerRef), JSON.stringify({
      evidence: { method_audit: { tdd: true } }
    }));

    expect(evaluateTerminalCompletionInvariant(fixture.state)).toEqual({
      passed: true,
      blockers: []
    });
  });
});

interface TerminalFixture {
  root: string;
  runRoot: string;
  workerRef: string;
  state: WaygentRunStateV2;
}

function writeTerminalFixture(runId: string): TerminalFixture {
  const root = mkdtempSync(join(tmpdir(), "waygent-terminal-root-"));
  const workspace = mkdtempSync(join(tmpdir(), "waygent-terminal-source-"));
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "before\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });

  const runRoot = join(root, runId);
  const worktree = mkdtempSync(join(tmpdir(), "waygent-terminal-worktree-"));
  Bun.spawnSync(["git", "clone", "--quiet", workspace, worktree]);
  writeFileSync(join(worktree, "a.txt"), "after\n");

  const taskPacket = writeArtifact(runRoot, "task_packets/task_a.json", JSON.stringify({ task_id: "task_a" }));
  const stdin = writeArtifact(runRoot, "provider/attempt_task_a_1.stdin.txt", "prompt", "text/plain");
  const stdout = writeArtifact(runRoot, "provider/attempt_task_a_1.stdout.txt", "{\"status\":\"completed\"}", "text/plain");
  const stderr = writeArtifact(runRoot, "provider/attempt_task_a_1.stderr.txt", "", "text/plain");
  const worker = writeArtifact(runRoot, "worker/task_a.json", JSON.stringify({ evidence: {} }));
  const kernel = writeArtifact(runRoot, "kernel/verify_task_a.json", JSON.stringify({ exit_code: 0 }));
  const checkpoint = createCheckpointArtifact({
    run_root: runRoot,
    run_id: runId,
    task_id: "task_a",
    candidate_id: "candidate_task_a",
    worktree_path: worktree,
    changed_files: ["a.txt"],
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
    provider_profile: { provider: "fake", execution_mode: "multi-agent" },
    method_evidence_required: false,
    status: "running",
    lifecycle_outcome: null,
    current_phase: "complete",
    tasks: {
      task_a: {
        id: "task_a",
        status: "verified",
        risk: "low",
        dependencies: [],
        file_claims: [{ path: "a.txt", mode: "owned" }],
        attempts: ["attempt_task_a_1"],
        task_packet_path: join(runRoot, taskPacket.path),
        task_packet_sha256: taskPacket.sha256,
        unit_manifest: { allowed_write_globs: ["a.txt"], forbidden_write_globs: [".git/**"] },
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
      command: "test -f a.txt",
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
      required_checks: ["test -f a.txt"],
      verification_evidence: [],
      review_evidence: [],
      checkpoint_evidence: [],
      combined_apply_evidence: combined,
      state_reconciliation: { passed: true, records: [], unrepaired_blockers: [] },
      residual_risk: [],
      prompt_to_artifact_checklist: []
    },
    timestamps: {
      started_at: "2026-05-21T00:00:00Z",
      updated_at: "2026-05-21T00:00:01Z",
      completed_at: null
    }
  };
  return { root, runRoot, workerRef: worker.path, state };
}
