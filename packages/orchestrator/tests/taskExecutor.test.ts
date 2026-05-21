import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { executeWaygentTask } from "../src/taskExecutor";
import { parseWaygentPlan } from "../src/planParser";
import { initSourceCheckout, oneTaskPlan } from "./support/orchestratorFixtures";

describe("executeWaygentTask", () => {
  test("returns task evidence without appending run events or flushing state", async () => {
    const workspace = initSourceCheckout("waygent-task-executor-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-task-executor-root-"));
    const parsed = parseWaygentPlan(oneTaskPlan("task_a", "a.txt"));
    const result = await executeWaygentTask({
      root,
      run_id: "run_task_executor",
      workspace,
      worktree_root: join(root, "worktrees"),
      task: parsed.tasks[0]!,
      checkpoint_inputs: [],
      spec: null,
      provider: "fake",
      provider_processes: {}
    });

    expect(result.task_id).toBe("task_a");
    expect(result.status).toBe("verified");
    expect(result.provider_attempt).toMatchObject({ task_id: "task_a", provider: "fake" });
    expect(result.verification_records.length).toBeGreaterThan(0);
    expect(result.checkpoint_refs[0]).toContain("artifacts/checkpoints/task_a/");
    expect(result.events.map((event) => event.event_type)).toContain("runway.worker_result");
    expect(result.worktree_manifest.task_id).toBe("task_a");
    expect(result.timing.duration_ms).toBeGreaterThanOrEqual(0);
    expect(result.phase_timings.map((timing) => timing.phase)).toEqual(
      expect.arrayContaining(["worktree_setup", "provider", "verification", "checkpoint", "checkpoint_dry_run", "total"])
    );
    expect(result.phase_timings.every((timing) => typeof timing.duration_ms === "number")).toBe(true);
  });

  test("blocks completed provider work when Waygent verification reports dependency_missing", async () => {
    const workspace = initSourceCheckout("waygent-task-executor-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-task-executor-root-"));
    const parsed = parseWaygentPlan([
      "```yaml waygent-task",
      "id: task_dependency_missing",
      "title: Create file with missing dependency verification",
      "dependencies: []",
      "file_claims:",
      "  - path: dep.txt",
      "    mode: owned",
      "risk: low",
      "verify:",
      "  - node -e \"throw new Error('Cannot find package ajv from validate.ts')\"",
      "```"
    ].join("\n"));

    const result = await executeWaygentTask({
      root,
      run_id: "run_dependency_missing",
      workspace,
      worktree_root: join(root, "worktrees"),
      task: parsed.tasks[0]!,
      checkpoint_inputs: [],
      spec: null,
      provider: "fake",
      provider_processes: {}
    });

    expect(result.status).toBe("blocked");
    expect(result.latest_failure_class).toBe("dependency_missing");
    expect(result.verification_records[0]).toMatchObject({
      failure_class: "dependency_missing",
      verification_environment: { status: "skipped" }
    });
    expect(result.events.find((event) => event.event_type === "runway.verification_result")?.payload).toMatchObject({
      failure_class: "dependency_missing"
    });
  });
});
