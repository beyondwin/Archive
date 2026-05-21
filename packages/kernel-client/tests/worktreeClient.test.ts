import { describe, expect, test } from "bun:test";
import { validateExplicitApply } from "../src";
import { buildApplyGuard, buildWorktreeBranch, planWorktree } from "../src/worktreeClient";

describe("worktree client", () => {
  test("refuses dirty source apply", () => {
    expect(validateExplicitApply({ run_id: "run_demo", source_dirty: true, checkpoint_ref: "checkpoint_demo" }).allowed).toBe(false);
  });
});

describe("worktree apply guard", () => {
  test("builds owned Waygent worktree branches", () => {
    expect(buildWorktreeBranch("run_demo", "task_demo")).toBe("waygent/run_demo/task_demo");
  });

  test("blocks apply on dirty source checkout", () => {
    expect(buildApplyGuard({ sourceDirty: true, merged: true, candidate_id: "candidate_demo", task_id: "task_demo" })).toMatchObject({
      can_apply: false,
      reason: "dirty_source_checkout",
    });
  });

  test("plans isolated worktree paths under a Waygent-owned branch", () => {
    expect(planWorktree({
      run_id: "run_demo",
      task_id: "task_demo",
      workspace: "/repo",
      worktree_root: "/tmp/waygent-worktrees"
    })).toEqual({
      branch: "waygent/run_demo/task_demo",
      path: "/tmp/waygent-worktrees/run_demo/task_demo",
      source: "/repo"
    });
  });
});
