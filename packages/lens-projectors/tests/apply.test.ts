import { describe, expect, test } from "bun:test";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { projectApplyReadinessFromState, projectApplyState } from "../src";
import { demoEvent } from "./support";

describe("apply projector", () => {
  test("reports verified but unapplied runs as apply-ready", () => {
    expect(projectApplyState([demoEvent({ event_type: "runway.verification_result", outcome: "success" })])).toEqual({
      status: "ready",
      reason: null
    });
  });

  test("reports dirty source checkout as blocked", () => {
    expect(
      projectApplyState([
        demoEvent({
          event_type: "runway.apply_blocked",
          outcome: "blocked",
          summary: "Dirty source checkout.",
          payload: { reason: "dirty_source_checkout" }
        })
      ])
    ).toEqual({
      status: "blocked",
      reason: "dirty_source_checkout"
    });
  });

  test("derives ready apply readiness from v2 state, completion audit, and combined patch evidence", () => {
    const state = makeState({
      apply: { status: "not_applied" },
      drift: { last_checked_at: "2026-05-21T00:00:00Z", records: [], unrepaired_blockers: [] },
      completion_audit: {
        status: "passed",
        combined_apply_evidence: {
          status: "passed",
          checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
          patch_ref: "artifacts/checkpoints/apply/run_ready.patch",
          patch_sha256: "a".repeat(64),
          patch_byte_length: 12,
          evidence_ref: "artifacts/checkpoints/apply-dry-run.json"
        }
      }
    });

    expect(projectApplyReadinessFromState(state)).toEqual({
      status: "ready",
      reason: null,
      checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
      combined_patch_ref: "artifacts/checkpoints/apply/run_ready.patch",
      source: "run_state_v2"
    });
  });

  test("blocks v2 apply readiness when reconciliation has unrepaired blockers", () => {
    const state = makeState({
      drift: {
        last_checked_at: "2026-05-21T00:00:00Z",
        records: [{ type: "artifact_missing", severity: "blocking" }],
        unrepaired_blockers: [{ type: "artifact_missing", severity: "blocking" }]
      },
      completion_audit: { status: "passed" }
    });

    expect(projectApplyReadinessFromState(state)).toMatchObject({
      status: "blocked",
      reason: "state_drift",
      source: "run_state_v2"
    });
  });

  test("reports failed task blocker before generic missing apply evidence", () => {
    const state = makeState({
      status: "blocked",
      lifecycle_outcome: "blocked",
      tasks: {
        task_a: {
          id: "task_a",
          status: "blocked",
          risk: "medium",
          dependencies: [],
          file_claims: [{ path: "front/feature.ts", mode: "owned" }],
          attempts: ["attempt_task_a_1"],
          task_packet_path: null,
          task_packet_sha256: null,
          unit_manifest: null,
          checkpoint_refs: [],
          latest_failure_class: "verification_failed",
          decision_packet_ref: null,
          timing: {}
        }
      },
      apply: { status: "blocked", reason: "missing_apply_ready_evidence" },
      completion_audit: {
        status: "failed",
        combined_apply_evidence: {
          status: "passed",
          checkpoint_refs: ["artifacts/checkpoints/task_base/candidate_task_base.json"],
          patch_ref: "artifacts/checkpoints/apply/run_partial.patch"
        }
      }
    });

    expect(projectApplyReadinessFromState(state)).toMatchObject({
      status: "blocked",
      reason: "verification_failed",
      checkpoint_refs: ["artifacts/checkpoints/task_base/candidate_task_base.json"],
      combined_patch_ref: "artifacts/checkpoints/apply/run_partial.patch"
    });
  });
});

function makeState(overrides: Partial<WaygentRunStateV2> = {}): WaygentRunStateV2 {
  return {
    schema: "waygent.run_state.v2",
    run_id: "run_demo",
    workspace: "/tmp/workspace",
    source_branch: "main",
    worktree_root: "/tmp/worktrees",
    run_root: "/tmp/run",
    artifact_root: "/tmp/run/artifacts",
    state_path: "/tmp/run/state.json",
    event_journal_path: "/tmp/run/events.jsonl",
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
        attempts: [],
        task_packet_path: null,
        task_packet_sha256: null,
        unit_manifest: null,
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        latest_failure_class: null,
        decision_packet_ref: null,
        timing: {}
      }
    },
    safe_waves: [],
    provider_attempts: [],
    reviews: [],
    verification: [],
    recovery: [],
    apply: { status: "not_ready" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: null,
    timestamps: {
      started_at: "2026-05-21T00:00:00Z",
      updated_at: "2026-05-21T00:00:00Z",
      completed_at: "2026-05-21T00:00:00Z"
    },
    ...overrides
  };
}
