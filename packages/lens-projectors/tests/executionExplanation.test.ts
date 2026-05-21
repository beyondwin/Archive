import { describe, expect, test } from "bun:test";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { projectExecutionExplanationFromState } from "../src";

describe("execution explanation projector", () => {
  test("explains waves, barriers, hotspots, and artifact health", () => {
    const projection = projectExecutionExplanationFromState(makeState({
      safe_waves: [
        {
          wave_id: "wave_1",
          ready: ["task_a"],
          concurrency: 1,
          timing: {
            started: "2026-05-22T00:00:00.000Z",
            completed: "2026-05-22T00:00:03.000Z",
            duration_ms: 3000
          },
          withheld: [{ task_id: "task_b", reason: "file_claim_conflict", detail: "README.md is already claimed" }]
        }
      ],
      artifact_index: [
        {
          ref: "artifacts/checkpoints/task_a/candidate_task_a.json",
          media_type: "application/json",
          sha256: "a".repeat(64),
          byte_length: 12,
          producer_phase: "checkpoint",
          task_id: "task_a",
          created_at: "2026-05-22T00:00:01.000Z"
        }
      ],
      tasks: {
        task_a: task("task_a", {
          phase_timings: [
            { phase: "provider", started: "2026-05-22T00:00:00.000Z", completed: "2026-05-22T00:00:02.000Z", duration_ms: 2000 }
          ]
        }),
        task_b: task("task_b", { status: "ready", checkpoint_refs: [] })
      },
      completion_audit: {
        status: "passed",
        combined_apply_evidence: {
          status: "passed",
          checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
          patch_ref: "artifacts/checkpoints/apply/run_demo.patch"
        }
      }
    }));

    expect(projection).toMatchObject({
      schema: "waygent.execution_explanation.v1",
      run_id: "run_demo",
      waves: [
        {
          wave_id: "wave_1",
          ready: ["task_a"],
          concurrency: 1,
          duration_ms: 3000,
          withheld: [{ task_id: "task_b", reason: "file_claim_conflict", detail: "README.md is already claimed" }]
        }
      ],
      barriers: [
        {
          task_id: "task_b",
          reason: "file_claim_conflict",
          category: "file_claim"
        }
      ],
      artifact_health: {
        indexed_count: 1,
        missing_count: 0,
        drift_count: 0,
        readiness_artifact_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json", "artifacts/checkpoints/apply/run_demo.patch"]
      }
    });
    expect(projection.cost_hotspots[0]).toMatchObject({ phase: "wave", duration_ms: 3000, wave_id: "wave_1" });
    expect(projection.recommended_next_actions).toContain("Split overlapping file claims or add dependencies so safe waves can stay parallel.");
  });

  test("summarizes drift records in artifact health", () => {
    const projection = projectExecutionExplanationFromState(makeState({
      drift: {
        last_checked_at: "2026-05-22T00:00:00.000Z",
        records: [
          { type: "state_drift", failure_class: "state_drift" },
          { type: "artifact_missing", failure_class: "artifact_missing" }
        ],
        unrepaired_blockers: []
      }
    }));

    expect(projection.artifact_health).toMatchObject({
      missing_count: 1,
      drift_count: 1
    });
  });
});

function task(id: string, overrides: Partial<WaygentRunStateV2["tasks"][string]> = {}): WaygentRunStateV2["tasks"][string] {
  return {
    id,
    status: "verified",
    risk: "low",
    dependencies: [],
    file_claims: [{ path: `${id}.txt`, mode: "owned" }],
    attempts: [],
    task_packet_path: null,
    task_packet_sha256: null,
    unit_manifest: null,
    checkpoint_refs: [`artifacts/checkpoints/${id}/candidate_${id}.json`],
    latest_failure_class: null,
    decision_packet_ref: null,
    timing: {},
    ...overrides
  };
}

function makeState(overrides: Partial<WaygentRunStateV2> = {}): WaygentRunStateV2 {
  return {
    schema: "waygent.run_state.v2",
    run_id: "run_demo",
    workspace: "/tmp/source",
    source_branch: "main",
    worktree_root: "/tmp/worktrees",
    run_root: "/tmp/run_demo",
    artifact_root: "/tmp/run_demo/artifacts",
    state_path: "/tmp/run_demo/state.json",
    event_journal_path: "/tmp/run_demo/events.jsonl",
    plan_path: null,
    spec_path: null,
    provider_profile: { provider: "fake" },
    status: "completed",
    lifecycle_outcome: "finished",
    current_phase: "complete",
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
      started_at: "2026-05-22T00:00:00.000Z",
      updated_at: "2026-05-22T00:00:03.000Z",
      completed_at: "2026-05-22T00:00:03.000Z"
    },
    ...overrides
  };
}
