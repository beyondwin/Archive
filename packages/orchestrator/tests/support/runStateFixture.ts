import { join } from "node:path";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { runStatePath } from "../../src/runState";

export function baseV2State(input: { root: string; run_id: string }): WaygentRunStateV2 {
  const runRoot = join(input.root, input.run_id);

  return {
    schema: "waygent.run_state.v2",
    run_id: input.run_id,
    workspace: input.root,
    source_branch: null,
    worktree_root: join(input.root, "worktrees"),
    run_root: runRoot,
    artifact_root: join(runRoot, "artifacts"),
    state_path: runStatePath(input.root, input.run_id),
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
