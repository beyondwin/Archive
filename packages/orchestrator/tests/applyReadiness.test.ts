import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, expect, test } from "bun:test";
import { appendEvent, sha256, writeArtifact } from "@waygent/lens-store";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { buildCompletionAudit, hasApplyReadyCheckpoint } from "../src/completionAudit";
import { buildRunEvent, resumeRun, verifyRun } from "../src/runCommands";
import { readRunStateV2, writeRunStateV2 } from "../src/runState";
import { baseV2State } from "./support/runStateFixture";

function writeFile(path: string, contents: string): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, contents);
}

function writePassedCheckpoint(state: WaygentRunStateV2, taskId: string): string {
  const patch = "";
  const patchArtifact = writeArtifact(
    state.run_root,
    `checkpoints/${taskId}/candidate_${taskId}.patch`,
    patch,
    "text/x-diff"
  );
  const dryRunEvidence = writeArtifact(
    state.run_root,
    `checkpoints/${taskId}/dry-run.json`,
    "{}\n",
    "application/json"
  );
  const manifest = {
    schema: "waygent.checkpoint_manifest.v1",
    run_id: state.run_id,
    task_id: taskId,
    candidate_id: `candidate_${taskId}`,
    patch_ref: patchArtifact.path,
    patch_sha256: patchArtifact.sha256,
    patch_byte_length: patchArtifact.byte_length,
    changed_files: ["README.md"],
    source_base: null,
    worktree_path: state.workspace,
    verification_refs: [`verification:${taskId}`],
    created_at: "2026-05-24T00:00:00.000Z",
    dry_run_status: "passed",
    dry_run_evidence_ref: dryRunEvidence.path
  };
  return writeArtifact(
    state.run_root,
    `checkpoints/${taskId}/candidate_${taskId}.json`,
    `${JSON.stringify(manifest, null, 2)}\n`
  ).path;
}

function combinedApplyEvidence(state: WaygentRunStateV2, checkpointRefs: string[]) {
  const patch = "";
  const patchRef = "artifacts/checkpoints/apply/combined.patch";
  writeFile(join(state.run_root, patchRef), patch);
  const evidenceRef = "artifacts/checkpoints/apply-dry-run.json";
  writeFile(join(state.run_root, evidenceRef), "{}\n");
  return {
    status: "passed" as const,
    checkpoint_refs: checkpointRefs,
    patch_ref: patchRef,
    patch_sha256: sha256(patch),
    patch_byte_length: new TextEncoder().encode(patch).byteLength,
    evidence_ref: evidenceRef,
    evidence_artifact: {
      path: evidenceRef,
      sha256: sha256("{}\n"),
      byte_length: new TextEncoder().encode("{}\n").byteLength,
      media_type: "application/json"
    }
  };
}

function addReadOnlyFinalTask(state: WaygentRunStateV2, status: WaygentRunStateV2["tasks"][string]["status"]): void {
  state.tasks.task_final_verification = {
    id: "task_final_verification",
    status,
    risk: "medium",
    dependencies: ["task_a"],
    file_claims: [{ path: "docs/plan.md", mode: "read_only" }],
    attempts: [],
    task_packet_path: null,
    task_packet_sha256: null,
    unit_manifest: { allowed_write_globs: [], forbidden_write_globs: [".git/**"] },
    checkpoint_refs: [],
    latest_failure_class: status === "verified" ? null : "verification_failed",
    decision_packet_ref: null,
    timing: {}
  };
}

function initVerificationWorktree(path: string): void {
  mkdirSync(path, { recursive: true });
  Bun.spawnSync(["git", "init", "-q"], { cwd: path });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: path });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: path });
  writeFileSync(join(path, "README.md"), "fixture\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: path });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: path });
}

function addActiveWorktree(state: WaygentRunStateV2, taskId: string, path: string): void {
  state.worktrees = [{
    task_id: taskId,
    path,
    source: state.workspace,
    source_commit: null,
    branch: "test",
    cleanup_status: "active"
  }];
}

function appendTrustEvent(state: WaygentRunStateV2): void {
  appendEvent(state.event_journal_path, buildRunEvent({
    run_id: state.run_id,
    sequence: 1,
    event_type: "lens.trust_report_updated",
    phase: "lens",
    outcome: "success",
    summary: "Trust report updated.",
    payload: {}
  }));
}

describe("apply readiness", () => {
  test("read-only final verification tasks do not require checkpoint artifacts", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-readonly-audit-"));
    const state = baseV2State({ root, run_id: "run_readonly_audit" });
    state.status = "completed";
    state.lifecycle_outcome = "finished";
    state.current_phase = "complete";
    state.tasks.task_a.status = "verified";
    state.tasks.task_a.checkpoint_refs = [writePassedCheckpoint(state, "task_a")];
    addReadOnlyFinalTask(state, "verified");
    const combined = combinedApplyEvidence(state, state.tasks.task_a.checkpoint_refs);

    state.completion_audit = buildCompletionAudit({
      state,
      required_checks: ["true"],
      verification_evidence: [{ task_id: "task_final_verification", status: "passed" }],
      review_evidence: [],
      combined_apply_evidence: combined,
      prompt_to_artifact_checklist: ["task_packet_written"]
    });

    expect(state.completion_audit).toMatchObject({ status: "passed", residual_risk: [] });
    expect(hasApplyReadyCheckpoint(state)).toBe(true);
  });

  test("empty file claims fail closed and still require checkpoint evidence", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-empty-claim-audit-"));
    const state = baseV2State({ root, run_id: "run_empty_claim_audit" });
    state.status = "completed";
    state.lifecycle_outcome = "finished";
    state.current_phase = "complete";
    state.tasks.task_a.status = "verified";
    state.tasks.task_a.file_claims = [];
    const combined = combinedApplyEvidence(state, []);

    state.completion_audit = buildCompletionAudit({
      state,
      required_checks: ["true"],
      verification_evidence: [{ task_id: "task_a", status: "passed" }],
      review_evidence: [],
      combined_apply_evidence: combined,
      prompt_to_artifact_checklist: ["task_packet_written"]
    });

    expect(state.completion_audit).toMatchObject({
      status: "failed",
      residual_risk: ["task_a:missing_checkpoint"]
    });
    expect(hasApplyReadyCheckpoint(state)).toBe(false);
  });

  test("successful verification rerun refreshes stale completion audit", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-rerun-audit-"));
    const state = baseV2State({ root, run_id: "run_rerun_audit" });
    const worktree = join(root, "worktree");
    initVerificationWorktree(worktree);
    const taskPacket = join(root, "task_final_verification.json");
    writeFile(taskPacket, `${JSON.stringify({ verification_commands: ["git diff --check"] })}\n`);
    state.status = "blocked";
    state.lifecycle_outcome = "blocked";
    state.current_phase = "recover";
    state.tasks.task_a.status = "verified";
    state.tasks.task_a.checkpoint_refs = [writePassedCheckpoint(state, "task_a")];
    addReadOnlyFinalTask(state, "blocked");
    state.tasks.task_final_verification.task_packet_path = taskPacket;
    addActiveWorktree(state, "task_final_verification", worktree);
    state.completion_audit = {
      status: "failed",
      combined_apply_evidence: combinedApplyEvidence(state, state.tasks.task_a.checkpoint_refs),
      residual_risk: ["task_final_verification:task_blocked"]
    };
    state.drift = {
      last_checked_at: "2026-05-24T00:00:00.000Z",
      records: [{ type: "artifact_missing", severity: "blocking", failure_class: "artifact_missing", message: "stale missing checkpoint", task_id: "task_final_verification" }],
      unrepaired_blockers: [{ type: "artifact_missing", severity: "blocking", failure_class: "artifact_missing", message: "stale missing checkpoint", task_id: "task_final_verification" }]
    };
    appendTrustEvent(state);
    writeRunStateV2(root, state);

    expect(await verifyRun({ root, run: state.run_id, task: "task_final_verification" })).toMatchObject({ status: "passed" });

    expect(readRunStateV2(root, state.run_id).drift.unrepaired_blockers).toEqual([]);
    expect(resumeRun({ root, run: state.run_id, dry_run: true }).allowed_actions).toContain("apply_verified_checkpoint");
  });

  test("read-only verification rerun blocks dirty worktrees instead of marking them verified", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-readonly-dirty-"));
    const state = baseV2State({ root, run_id: "run_readonly_dirty" });
    const worktree = join(root, "worktree");
    initVerificationWorktree(worktree);
    writeFileSync(join(worktree, "README.md"), "dirty\n");
    const taskPacket = join(root, "task_final_verification.json");
    writeFile(taskPacket, `${JSON.stringify({ verification_commands: ["test -f README.md"] })}\n`);
    state.status = "blocked";
    state.lifecycle_outcome = "blocked";
    state.current_phase = "recover";
    state.tasks.task_a.status = "verified";
    state.tasks.task_a.checkpoint_refs = [writePassedCheckpoint(state, "task_a")];
    addReadOnlyFinalTask(state, "blocked");
    state.tasks.task_final_verification.task_packet_path = taskPacket;
    addActiveWorktree(state, "task_final_verification", worktree);
    state.completion_audit = {
      status: "failed",
      combined_apply_evidence: combinedApplyEvidence(state, state.tasks.task_a.checkpoint_refs),
      residual_risk: ["task_final_verification:task_blocked"]
    };
    writeRunStateV2(root, state);

    expect(await verifyRun({ root, run: state.run_id, task: "task_final_verification" })).toMatchObject({
      status: "failed",
      failure_class: "state_drift"
    });
    expect(resumeRun({ root, run: state.run_id, dry_run: true }).allowed_actions).not.toContain("apply_verified_checkpoint");
  });
});
