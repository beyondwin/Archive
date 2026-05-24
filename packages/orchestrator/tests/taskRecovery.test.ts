import { describe, expect, test } from "bun:test";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { appendSchedulerRecovery } from "../src/taskRecovery";

describe("appendSchedulerRecovery", () => {
  test("schedules strict retry for malformed_result", () => {
    const state = runStateFixture();
    const result = appendSchedulerRecovery({
      state,
      task_id: "task_1",
      failure_class: "malformed_result",
      prior_summary: "provider returned prose",
      evidence_refs: ["worker/task_1.json"]
    });

    expect(result.decision.action).toBe("retry_with_strict_prompt");
    expect(state.recovery[0]).toMatchObject({
      task_id: "task_1",
      failure_class: "malformed_result",
      automatic: true,
      result: "scheduled"
    });
  });

  test("blocks after attempts are exhausted", () => {
    const state = runStateFixture({
      recovery: [
        { task_id: "task_1", failure_class: "malformed_result", action: "retry_with_strict_prompt", attempt_number: 1 },
        { task_id: "task_1", failure_class: "malformed_result", action: "retry_with_strict_prompt", attempt_number: 2 }
      ]
    });

    const result = appendSchedulerRecovery({
      state,
      task_id: "task_1",
      failure_class: "malformed_result",
      prior_summary: "still malformed",
      evidence_refs: []
    });

    expect(result.decision.action).toBe("request_decision");
    expect(result.record.result).toBe("blocked");
  });
});

function runStateFixture(overrides: Partial<WaygentRunStateV2> = {}): WaygentRunStateV2 {
  return {
    schema: "waygent.run_state.v2",
    run_id: "run_recovery",
    workspace: "/tmp/waygent-recovery-state",
    source_branch: null,
    worktree_root: "/tmp/waygent-recovery-state/worktrees",
    run_root: "/tmp/waygent-recovery-state/run_recovery",
    artifact_root: "/tmp/waygent-recovery-state/run_recovery/artifacts",
    state_path: "/tmp/waygent-recovery-state/run_recovery/state.json",
    event_journal_path: "/tmp/waygent-recovery-state/run_recovery/events.jsonl",
    plan_path: null,
    spec_path: null,
    provider_profile: { provider: "fake" },
    status: "running",
    lifecycle_outcome: null,
    current_phase: "recover",
    worktrees: [],
    artifact_index: [],
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
      started_at: "2026-05-21T00:00:00.000Z",
      updated_at: "2026-05-21T00:00:00.000Z",
      completed_at: null
    },
    ...overrides
  };
}
