import { describe, expect, test } from "bun:test";
import type { AgentLensEvent, WaygentRunStateV2 } from "@waygent/contracts";
import { projectRunReadModel } from "../src";
import { demoEvent } from "./support";

describe("run read model projector", () => {
  test("prefers v2 state status and apply readiness over stale event-derived state", () => {
    const state = makeState({
      status: "blocked",
      lifecycle_outcome: "blocked",
      apply: { status: "blocked", reason: "needs_rebase" },
      tasks: {
        task_a: task({ status: "blocked", checkpoint_refs: [], latest_failure_class: "needs_rebase" })
      },
      completion_audit: { status: "failed" }
    });
    const model = projectRunReadModel({
      run_id: state.run_id,
      state,
      events: [
        event("platform.run_started", "running"),
        event("runway.verification_result", "success"),
        event("lens.trust_report_updated", "success")
      ]
    });

    expect(model.status).toBe("blocked");
    expect(model.apply_status).toBe("blocked");
    expect(model.apply_readiness).toMatchObject({
      status: "blocked",
      reason: "needs_rebase",
      checkpoint_refs: [],
      source: "run_state_v2"
    });
    expect(model.operational_maturity?.hard_blocker).toMatchObject({
      task_id: "task_a",
      failure_class: "needs_rebase"
    });
  });

  test("keeps missing v2 state as an explicit read blocker without inferring apply readiness", () => {
    const model = projectRunReadModel({
      run_id: "run_missing_state",
      events: [event("runway.verification_result", "success")],
      state_error: { status: "missing", reason: "missing_run_state_v2" }
    });

    expect(model.status).toBe("completed");
    expect(model.apply_status).toBe("not_ready");
    expect(model.apply_readiness).toBeNull();
    expect(model.state_blocker).toEqual({ status: "missing", reason: "missing_run_state_v2" });
  });
});

function event(eventType: string, outcome: AgentLensEvent["outcome"]): AgentLensEvent {
  return demoEvent({ event_type: eventType, outcome });
}

function makeState(overrides: Partial<WaygentRunStateV2> = {}): WaygentRunStateV2 {
  return {
    schema: "waygent.run_state.v2",
    run_id: "run_read_model",
    workspace: "/tmp/workspace",
    source_branch: "main",
    worktree_root: "/tmp/worktrees",
    run_root: "/tmp/run_read_model",
    artifact_root: "/tmp/run_read_model/artifacts",
    state_path: "/tmp/run_read_model/state.json",
    event_journal_path: "/tmp/run_read_model/events.jsonl",
    plan_path: null,
    spec_path: null,
    provider_profile: { provider: "fake" },
    status: "completed",
    lifecycle_outcome: "finished",
    current_phase: "complete",
    tasks: { task_a: task() },
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
      started_at: "2026-05-22T00:00:00.000Z",
      updated_at: "2026-05-22T00:00:01.000Z",
      completed_at: "2026-05-22T00:00:01.000Z"
    },
    ...overrides
  };
}

function task(overrides: Partial<WaygentRunStateV2["tasks"][string]> = {}): WaygentRunStateV2["tasks"][string] {
  return {
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
    timing: {},
    ...overrides
  };
}
