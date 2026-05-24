import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
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

  test("verifies and checkpoints RED-only tasks with explicit expected-failure commands", async () => {
    const workspace = initSourceCheckout("waygent-task-executor-red-verify-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-task-executor-red-verify-root-"));
    const parsed = parseWaygentPlan([
      "```yaml waygent-task",
      "id: task_red_contract",
      "title: Lock expected failure contract",
      "dependencies: []",
      "file_claims:",
      "  - path: red.txt",
      "    mode: owned",
      "risk: low",
      "verify_fail:",
      "  - test -f missing-red-contract.txt",
      "```"
    ].join("\n"));

    const result = await executeWaygentTask({
      root,
      run_id: "run_red_contract",
      workspace,
      worktree_root: join(root, "worktrees"),
      task: parsed.tasks[0]!,
      checkpoint_inputs: [],
      spec: null,
      provider: "fake",
      provider_processes: {}
    });

    expect(result.status).toBe("verified");
    expect(result.latest_failure_class).toBeNull();
    expect(result.checkpoint_refs[0]).toContain("artifacts/checkpoints/task_red_contract/");
    expect(result.verification_records[0]).toMatchObject({
      status: "passed",
      expected_exit: "nonzero"
    });
  });

  test("accepts provider self-reported environment blockers when kernel verification passes", async () => {
    const workspace = initSourceCheckout("waygent-task-executor-provider-env-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-task-executor-provider-env-root-"));
    const parsed = parseWaygentPlan([
      "```yaml waygent-task",
      "id: task_provider_env",
      "title: Provider reports local env blocker after writing valid output",
      "dependencies: []",
      "file_claims:",
      "  - path: env.txt",
      "    mode: owned",
      "risk: low",
      "verify:",
      "  - test -f env.txt",
      "```"
    ].join("\n"));
    const script = `
      const { writeFileSync } = require("node:fs");
      const { join } = require("node:path");
      writeFileSync(join(process.cwd(), "env.txt"), "verified by kernel\\n");
      console.log(JSON.stringify({
        schema: "runway.worker_result.v1",
        task_id: "task_provider_env",
        candidate_id: "candidate_task_provider_env",
        status: "blocked",
        changed_files: ["env.txt"],
        summary: "provider local typecheck missed dependencies after writing valid output",
        evidence: { local_typecheck: "dependency_missing" },
        failure_class: "dependency_missing"
      }));
    `;

    const result = await executeWaygentTask({
      root,
      run_id: "run_provider_env",
      workspace,
      worktree_root: join(root, "worktrees"),
      task: parsed.tasks[0]!,
      checkpoint_inputs: [],
      spec: null,
      provider: "codex",
      provider_processes: { codex: { executable: process.execPath, args: ["-e", script] } }
    });

    expect(result.status).toBe("verified");
    expect(result.latest_failure_class).toBeNull();
    expect(result.checkpoint_refs[0]).toContain("artifacts/checkpoints/task_provider_env/");
    expect(result.events.find((event) => event.event_type === "runway.worker_result")).toMatchObject({
      outcome: "success",
      payload: {
        failure_class: null,
        provider_reported_failure_class: "dependency_missing"
      }
    });
    expect(result.events.find((event) => event.event_type === "runway.verification_result")).toMatchObject({
      outcome: "success",
      payload: {
        failure_class: null
      }
    });
  });

  test("materializes dependency checkpoints as dependent task worktree baseline", async () => {
    const workspace = initSourceCheckout("waygent-task-executor-checkpoint-input-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-task-executor-checkpoint-input-root-"));
    const base = parseWaygentPlan(oneTaskPlan("task_base", "base.txt"));
    const baseResult = await executeWaygentTask({
      root,
      run_id: "run_checkpoint_input",
      workspace,
      worktree_root: join(root, "worktrees"),
      task: base.tasks[0]!,
      checkpoint_inputs: [],
      spec: null,
      provider: "fake",
      provider_processes: {}
    });
    expect(baseResult.status).toBe("verified");
    const dependencyCheckpoint = baseResult.checkpoint_refs[0]!;

    const dependent = parseWaygentPlan([
      "```yaml waygent-task",
      "id: task_dependent",
      "title: Create dependent output using checkpoint input",
      "dependencies: [task_base]",
      "file_claims:",
      "  - path: dependent.txt",
      "    mode: owned",
      "risk: low",
      "verify:",
      "  - test -f base.txt && test -f dependent.txt",
      "```"
    ].join("\n"));

    const result = await executeWaygentTask({
      root,
      run_id: "run_checkpoint_input",
      workspace,
      worktree_root: join(root, "worktrees"),
      task: dependent.tasks[0]!,
      checkpoint_inputs: [dependencyCheckpoint],
      spec: null,
      provider: "fake",
      provider_processes: {}
    });

    expect(result.status).toBe("verified");
    expect(result.latest_failure_class).toBeNull();
    expect(result.checkpoint_refs[0]).toContain("artifacts/checkpoints/task_dependent/");
    const patch = readFileSync(join(root, "run_checkpoint_input", result.checkpoint_refs[0]!.replace(/\.json$/, ".patch")), "utf8");
    expect(patch).toContain("dependent.txt");
    expect(patch).not.toContain("base.txt");
  });

  test("blocks red task packets before provider dispatch", async () => {
    const workspace = initSourceCheckout("waygent-task-executor-red-context-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-task-executor-red-context-root-"));
    const parsed = parseWaygentPlan([
      "```yaml waygent-task",
      "id: task_red_context",
      "title: Create red context output",
      "dependencies: []",
      "file_claims:",
      "  - path: red.txt",
      "    mode: owned",
      "risk: low",
      "instructions:",
      `  - ${"Include compact context only. ".repeat(80)}`,
      "verify:",
      "  - test -f red.txt",
      "```"
    ].join("\n"));

    const result = await executeWaygentTask({
      root,
      run_id: "run_red_context",
      workspace,
      worktree_root: join(root, "worktrees"),
      task: parsed.tasks[0]!,
      checkpoint_inputs: [],
      spec: null,
      provider: "fake",
      provider_processes: {},
      task_packet_max_chars: 500
    });

    expect(result.status).toBe("blocked");
    expect(result.latest_failure_class).toBe("context_missing");
    expect(result.events.map((event) => event.event_type)).toContain("context.packet_budget_evaluated");
    expect(result.events.map((event) => event.event_type)).not.toContain("runway.worker_result");
  });

  test("records needs_rebase when checkpoint dry-run conflicts with the source basis", async () => {
    const workspace = initSourceCheckout("waygent-task-executor-conflict-source-");
    writeFileSync(join(workspace, "README.md"), "source advanced outside task worktree\n");
    const root = mkdtempSync(join(tmpdir(), "waygent-task-executor-conflict-root-"));
    const parsed = parseWaygentPlan(oneTaskPlan("task_conflict", "README.md"));

    const result = await executeWaygentTask({
      root,
      run_id: "run_task_conflict",
      workspace,
      worktree_root: join(root, "worktrees"),
      task: parsed.tasks[0]!,
      checkpoint_inputs: [],
      spec: null,
      provider: "fake",
      provider_processes: {}
    });

    const dryRunEvent = result.events.find((event) => event.event_type === "runway.apply_dry_run_result");
    expect(result.status).toBe("blocked");
    expect(result.latest_failure_class).toBe("needs_rebase");
    expect(result.checkpoint_refs).toEqual([]);
    expect(result.artifact_index_entries.map((entry) => entry.producer_phase)).toContain("checkpoint");
    expect(dryRunEvent).toMatchObject({
      outcome: "blocked",
      payload: {
        task_id: "task_conflict",
        dry_run: {
          status: "failed",
          failure_class: "needs_rebase",
          failed_files: ["README.md"]
        }
      }
    });
  });
});
