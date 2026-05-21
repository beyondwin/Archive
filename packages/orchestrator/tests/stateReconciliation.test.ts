import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { writeRunStateV2 } from "../src/runState";
import { reconcileRunState } from "../src/stateReconciliation";

describe("Waygent state reconciliation", () => {
  test("blocks finished states missing task packet artifacts", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-reconcile-"));
    const runRoot = join(root, "run_drift");
    mkdirSync(runRoot, { recursive: true });
    writeRunStateV2(root, {
      schema: "waygent.run_state.v2",
      run_id: "run_drift",
      workspace: root,
      source_branch: "main",
      worktree_root: join(root, "worktrees"),
      run_root: runRoot,
      artifact_root: join(runRoot, "artifacts"),
      state_path: join(runRoot, "state.json"),
      event_journal_path: join(runRoot, "events.jsonl"),
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
          task_packet_path: join(runRoot, "artifacts", "task_packets", "task_a.json"),
          task_packet_sha256: null,
          unit_manifest: { allowed_write_globs: ["README.md"] },
          checkpoint_refs: ["checkpoint_task_a"],
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
      apply: { status: "not_applied" },
      context: { snapshot_path: null, basis_hash: null },
      drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
      completion_audit: { status: "passed" },
      timestamps: {
        started_at: "2026-05-21T00:00:00Z",
        updated_at: "2026-05-21T00:00:00Z",
        completed_at: "2026-05-21T00:00:00Z"
      }
    });
    writeFileSync(join(runRoot, "events.jsonl"), "");

    const report = reconcileRunState(root, "run_drift");

    expect(report.passed).toBe(false);
    expect(report.unrepaired_blockers[0]?.type).toBe("artifact_missing");
  });
});
