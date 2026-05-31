import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import type { TaskReviewArtifact, WaygentRunStateV2 } from "@waygent/contracts";
import { reviewEvidenceMissing, reviewEvidencePolicy } from "../src/reviewEvidence";

describe("review evidence policy", () => {
  test("requires review for high-risk tasks", () => {
    const state = baseV2State({ root: mkdtempSync(join(tmpdir(), "waygent-review-evidence-")), run_id: "run_review_policy" });
    state.tasks.task_a.risk = "high";
    state.tasks.task_a.status = "verified";
    state.tasks.task_a.checkpoint_refs = ["checkpoint/task_a.json"];

    expect(reviewEvidencePolicy(state)).toMatchObject({ required: true, reason: "high_risk_task" });
    expect(reviewEvidenceMissing({ state, review_evidence: [] })).toBe("high_risk_task");
  });

  test("requires review for broad claims, multi-package touches, and strict mode", () => {
    const state = baseV2State({ root: mkdtempSync(join(tmpdir(), "waygent-review-policy-full-")), run_id: "run_review_policy_full" });
    state.provider_profile = { provider: "fake", review_mode: "strict" };
    state.tasks.task_a.file_claims = [
      { path: "packages/orchestrator/src/reviewEvidence.ts", mode: "owned" },
      { path: "packages/lens-projectors/src/apply.ts", mode: "owned" }
    ];

    expect(reviewEvidencePolicy(state)).toMatchObject({
      required: true,
      reason: "strict_review_mode",
      required_task_ids: ["task_a"],
      task_reasons: {
        task_a: expect.arrayContaining(["strict_review_mode", "multi_package_touch"])
      }
    });
  });

  test("requires review after recovery attempts", () => {
    const state = baseV2State({ root: mkdtempSync(join(tmpdir(), "waygent-review-recovery-")), run_id: "run_review_recovery" });
    state.recovery.push({
      task_id: "task_a",
      failure_class: "verification_failed",
      action: "retry_with_evidence",
      attempt_number: 1
    });

    expect(reviewEvidencePolicy(state)).toMatchObject({ required: true, reason: "recovery_attempted" });
    expect(reviewEvidenceMissing({ state, review_evidence: [] })).toBe("recovery_attempted");
  });

  test("accepts approved spec and quality review artifacts", () => {
    const state = baseV2State({ root: mkdtempSync(join(tmpdir(), "waygent-review-present-")), run_id: "run_review_present" });
    state.method_evidence_required = true;

    expect(reviewEvidenceMissing({
      state,
      review_evidence: [
        taskReview({ run_id: state.run_id, task_id: "task_a", role: "spec_reviewer" }),
        taskReview({ run_id: state.run_id, task_id: "task_a", role: "quality_reviewer" })
      ]
    })).toBeNull();
  });

  test("fails closed when required review evidence is incomplete or rejected", () => {
    const state = baseV2State({ root: mkdtempSync(join(tmpdir(), "waygent-review-rejected-")), run_id: "run_review_rejected" });
    state.tasks.task_a.risk = "high";

    expect(reviewEvidenceMissing({
      state,
      review_evidence: [taskReview({ run_id: state.run_id, task_id: "task_a", role: "spec_reviewer" })]
    })).toBe("task_a:missing_review_artifact");
    expect(reviewEvidenceMissing({
      state,
      review_evidence: [
        taskReview({ run_id: state.run_id, task_id: "task_a", role: "spec_reviewer" }),
        taskReview({ run_id: state.run_id, task_id: "task_a", role: "quality_reviewer", status: "needs_fix", verdict: "rejected" })
      ]
    })).toBe("task_a:review_failed");
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
    issues: [],
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
