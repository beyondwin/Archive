import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { prepareManagedTaskWorktree } from "../src/worktreeManager";
import { initSourceCheckout } from "./support/orchestratorFixtures";

describe("WorktreeManager", () => {
  test("prepares an isolated task worktree and records setup timing", () => {
    const workspace = initSourceCheckout("waygent-worktree-manager-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-worktree-manager-root-"));

    const result = prepareManagedTaskWorktree({
      run_id: "run_worktree",
      task_id: "task_a",
      workspace,
      worktree_root: join(root, "worktrees")
    });

    expect(existsSync(result.manifest.path)).toBe(true);
    expect(result.manifest.task_id).toBe("task_a");
    expect(result.manifest.cleanup_status).toBe("active");
    expect(result.timing).toMatchObject({
      phase: "worktree_setup",
      duration_ms: expect.any(Number)
    });
  });
});
