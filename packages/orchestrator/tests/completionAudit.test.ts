import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, expect, test } from "bun:test";
import type { TaskReviewArtifact, WaygentRunStateV2 } from "@waygent/contracts";
import { buildCompletionAudit, hasApplyReadyCheckpoint } from "../src/completionAudit";

function writeFile(path: string, contents: string): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, contents);
}

function writeArtifact(runRoot: string, relPath: string, contents: string, mediaType = "application/json") {
  const path = join("artifacts", relPath);
  const absolutePath = join(runRoot, path);
  writeFile(absolutePath, contents);
  return {
    path,
    sha256: sha256(contents),
    byte_length: new TextEncoder().encode(contents).byteLength,
    media_type: mediaType
  };
}

function sha256(data: string): string {
  return createHash("sha256").update(data).digest("hex");
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
    created_at: "2026-05-31T00:00:00.000Z",
    dry_run_status: "passed",
    dry_run_evidence_ref: dryRunEvidence.path
  };
  return writeArtifact(
    state.run_root,
    `checkpoints/${taskId}/candidate_${taskId}.json`,
    `${JSON.stringify(manifest, null, 2)}\n`,
    "application/json"
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

describe("completion audit", () => {
  test("reports recovery review obligations before generic apply readiness blockers", () => {
    const state = baseV2State({ root: mkdtempSync(join(tmpdir(), "waygent-completion-review-missing-")), run_id: "run_completion_review_missing" });
    state.tasks.task_a.status = "verified";
    state.tasks.task_a.checkpoint_refs = [writePassedCheckpoint(state, "task_a")];
    state.recovery.push({
      task_id: "task_a",
      failure_class: "verification_failed",
      action: "retry_with_evidence",
      attempt_number: 1
    });
    const combined = combinedApplyEvidence(state, state.tasks.task_a.checkpoint_refs);

    const audit = buildCompletionAudit({
      state,
      required_checks: ["bun test"],
      verification_evidence: [{ task_id: "task_a", status: "passed" }],
      review_evidence: [],
      combined_apply_evidence: combined,
      prompt_to_artifact_checklist: ["task_packet_written"]
    });

    expect(audit).toMatchObject({
      status: "failed",
      review_status: {
        required: true,
        reason: "recovery_attempted",
        missing_task_ids: ["task_a"]
      },
      residual_risk: ["review_evidence:recovery_attempted"]
    });
  });

  test("passes only when required spec and quality review artifacts approve the task", () => {
    const state = baseV2State({ root: mkdtempSync(join(tmpdir(), "waygent-completion-review-passed-")), run_id: "run_completion_review_passed" });
    state.tasks.task_a.status = "verified";
    state.tasks.task_a.risk = "high";
    state.tasks.task_a.checkpoint_refs = [writePassedCheckpoint(state, "task_a")];
    const combined = combinedApplyEvidence(state, state.tasks.task_a.checkpoint_refs);

    state.completion_audit = buildCompletionAudit({
      state,
      required_checks: ["bun test"],
      verification_evidence: [{ task_id: "task_a", status: "passed" }],
      review_evidence: [
        taskReview({ run_id: state.run_id, task_id: "task_a", role: "spec_reviewer" }),
        taskReview({ run_id: state.run_id, task_id: "task_a", role: "quality_reviewer" })
      ],
      combined_apply_evidence: combined,
      prompt_to_artifact_checklist: ["task_packet_written"]
    });

    expect(state.completion_audit).toMatchObject({
      status: "passed",
      review_status: {
        required: true,
        passed_task_ids: ["task_a"],
        missing_task_ids: []
      },
      residual_risk: []
    });
    expect(hasApplyReadyCheckpoint(state)).toBe(true);
  });

  test("failed review artifacts block completion audit even when verification and checkpoints passed", () => {
    const state = baseV2State({ root: mkdtempSync(join(tmpdir(), "waygent-completion-review-failed-")), run_id: "run_completion_review_failed" });
    state.tasks.task_a.status = "verified";
    state.tasks.task_a.risk = "high";
    state.tasks.task_a.checkpoint_refs = [writePassedCheckpoint(state, "task_a")];
    const combined = combinedApplyEvidence(state, state.tasks.task_a.checkpoint_refs);

    const audit = buildCompletionAudit({
      state,
      required_checks: ["bun test"],
      verification_evidence: [{ task_id: "task_a", status: "passed" }],
      review_evidence: [
        taskReview({ run_id: state.run_id, task_id: "task_a", role: "spec_reviewer" }),
        taskReview({ run_id: state.run_id, task_id: "task_a", role: "quality_reviewer", status: "needs_fix", verdict: "rejected" })
      ],
      combined_apply_evidence: combined,
      prompt_to_artifact_checklist: ["task_packet_written"]
    });

    expect(audit).toMatchObject({
      status: "failed",
      review_status: {
        failed_task_ids: ["task_a"]
      },
      residual_risk: ["review_evidence:task_a:review_failed"]
    });
  });
});

function taskReview(input: {
  run_id: string;
  task_id: string;
  role: "spec_reviewer" | "quality_reviewer";
  status?: "passed" | "failed" | "needs_fix";
  verdict?: "approved" | "rejected";
}): TaskReviewArtifact {
  return {
    schema: "waygent.task_review.v1",
    run_id: input.run_id,
    task_id: input.task_id,
    review_id: `${input.task_id}_${input.role}`,
    role: input.role,
    status: input.status ?? "passed",
    verdict: input.verdict ?? "approved",
    issues: input.verdict === "rejected"
      ? [{ severity: "important", summary: "Needs a focused fix.", required_fix: "Repair the reviewed patch." }]
      : [],
    evidence_refs: ["artifacts/worker/result.json"],
    reviewed_patch_refs: ["artifacts/checkpoints/task_a/candidate_task_a.patch"],
    created_at: "2026-05-31T00:00:00.000Z"
  };
}

function baseV2State(input: { root: string; run_id: string }): WaygentRunStateV2 {
  const runRoot = join(input.root, input.run_id);
  return {
    schema: "waygent.run_state.v2",
    run_id: input.run_id,
    workspace: input.root,
    source_branch: null,
    worktree_root: join(input.root, "worktrees"),
    run_root: runRoot,
    artifact_root: join(runRoot, "artifacts"),
    state_path: join(runRoot, "state.json"),
    event_journal_path: join(runRoot, "events.jsonl"),
    plan_path: null,
    spec_path: null,
    provider_profile: { provider: "fake" },
    status: "running",
    lifecycle_outcome: null,
    current_phase: "preflight",
    worktrees: [],
    tasks: {
      task_a: {
        id: "task_a",
        status: "ready",
        risk: "low",
        dependencies: [],
        file_claims: [{ path: "a.txt", mode: "owned" }],
        attempts: [],
        task_packet_path: null,
        task_packet_sha256: null,
        unit_manifest: { allowed_write_globs: ["a.txt"], forbidden_write_globs: [".git/**"] },
        checkpoint_refs: [],
        latest_failure_class: null,
        decision_packet_ref: null,
        timing: {}
      }
    },
    safe_waves: [{ wave_id: "wave_1", ready: ["task_a"], withheld: [] }],
    provider_attempts: [],
    reviews: [],
    verification: [],
    recovery: [],
    apply: { status: "not_applied" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: null,
    timestamps: {
      started_at: "2026-05-21T00:00:00.000Z",
      updated_at: "2026-05-21T00:00:00.000Z",
      completed_at: null
    }
  };
}
