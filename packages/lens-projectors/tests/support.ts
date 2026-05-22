import type { AgentLensEvent, WaygentRunStateV2 } from "@waygent/contracts";

export function demoEvent(overrides: Partial<AgentLensEvent> = {}): AgentLensEvent {
  return {
    schema: "agentlens.event.v3",
    event_id: `event_demo_${overrides.sequence ?? 1}`,
    agentlens_run_id: "run_lens",
    orchestrator_run_id: "run_demo",
    producer: { name: "waygent", kind: "orchestrator", version: "0.1.0" },
    event_type: "runway.verification_result",
    occurred_at: "2026-05-21T00:00:00Z",
    sequence: 1,
    phase: "verify",
    outcome: "success",
    severity: "info",
    trust_impact: "supports_success",
    summary: "Verification passed.",
    payload: { task_id: "task_demo" },
    ...overrides
  };
}

export function stateFixture(overrides: Partial<WaygentRunStateV2> & {
  tasks?: Record<string, Partial<WaygentRunStateV2["tasks"][string]>>;
} = {}): WaygentRunStateV2 {
  const baseTask: WaygentRunStateV2["tasks"][string] = {
    id: "task_demo",
    status: "verified",
    risk: "low",
    dependencies: [],
    file_claims: [{ path: "README.md", mode: "owned" }],
    attempts: [],
    task_packet_path: null,
    task_packet_sha256: null,
    unit_manifest: null,
    checkpoint_refs: [],
    latest_failure_class: null,
    decision_packet_ref: null,
    timing: {}
  };
  const state: WaygentRunStateV2 = {
    schema: "waygent.run_state.v2",
    run_id: "run_demo",
    workspace: "/tmp/workspace",
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
    tasks: { task_demo: baseTask },
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
      updated_at: "2026-05-22T00:00:00.000Z",
      completed_at: "2026-05-22T00:00:00.000Z"
    }
  };
  return {
    ...state,
    ...overrides,
    tasks: Object.fromEntries(Object.entries(overrides.tasks ?? state.tasks).map(([id, task]) => [
      id,
      { ...baseTask, id, ...task }
    ]))
  };
}
