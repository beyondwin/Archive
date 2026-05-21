import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readRunState, writeRunState } from "../src/runState";

describe("Waygent run state", () => {
  test("persists lifecycle, worktree, task, and audit metadata", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-state-"));
    writeRunState(root, {
      schema: "waygent.run_state.v1",
      run_id: "run_state",
      workspace: "/workspace",
      worktree: "/worktree",
      status: "completed",
      provider: "fake",
      execution_mode: "multi-agent",
      tasks: [{ id: "task_a", status: "verified", checkpoint_ref: "checkpoint_task_a" }],
      completion_audit: {
        status: "passed",
        commands: ["printf hello"],
        evidence_events: ["event_run_state_5"]
      },
      apply: { status: "not_applied" }
    });

    expect(readRunState(root, "run_state")).toMatchObject({
      run_id: "run_state",
      status: "completed",
      tasks: [{ id: "task_a", status: "verified" }],
      completion_audit: { status: "passed" }
    });
  });
});
