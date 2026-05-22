import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { deriveRunId, RUN_ID_COLLISION_MAX_RETRIES } from "../../../packages/orchestrator/src/runIdDerivation";
import { runCli } from "../src/index";

const plan = `
\`\`\`yaml waygent-task
id: task_collision
title: Collision retry
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`;

function initSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  writeFileSync(join(workspace, "README.md"), "fixture\n");
  for (const args of [
    ["init", "-q"],
    ["config", "user.email", "test@example.com"],
    ["config", "user.name", "Waygent"],
    ["add", "-A"],
    ["commit", "-q", "-m", "init"]
  ]) {
    const result = Bun.spawnSync(["git", ...args], { cwd: workspace });
    if (result.exitCode !== 0) throw new Error(`git ${args.join(" ")} failed`);
  }
  return workspace;
}

function occupyRunDir(root: string, runId: string): void {
  const runDir = join(root, runId);
  mkdirSync(runDir, { recursive: true });
  writeFileSync(join(runDir, "events.jsonl"), "existing evidence\n");
}

function candidateBasesForWindow(planPath: string, windowSeconds: number): string[] {
  const now = Date.now();
  const ids = new Set<string>();
  for (let dt = 0; dt <= windowSeconds; dt += 1) {
    ids.add(deriveRunId({ plan_path: planPath, now: new Date(now + dt * 1000) }));
  }
  return Array.from(ids);
}

describe("CLI run_id collision retry", () => {
  test("appends a numeric suffix when the derived id is already occupied", async () => {
    const workspace = initSourceCheckout("waygent-collision-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-collision-root-"));
    const planName = "2026-05-22-collision-plan.md";
    writeFileSync(join(workspace, planName), plan);

    const occupiedBases = candidateBasesForWindow(planName, 10);
    for (const id of occupiedBases) occupyRunDir(root, id);

    const result = await runCli([
      "run",
      "--provider", "fake",
      "--workspace", workspace,
      "--root", root,
      "--plan", planName
    ]) as { run_id: string };

    expect(result.run_id).toMatch(/^collision_plan_\d{8}_\d{6}_\d+$/);
    expect(occupiedBases).not.toContain(result.run_id);
  });

  test("throws run_id_collision_unresolved when every retry slot is occupied", async () => {
    const workspace = initSourceCheckout("waygent-collision-exhaust-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-collision-exhaust-root-"));
    const planName = "exhaust-plan.md";
    writeFileSync(join(workspace, planName), plan);

    const bases = candidateBasesForWindow(planName, 5);
    for (const base of bases) {
      occupyRunDir(root, base);
      for (let suffix = 1; suffix <= RUN_ID_COLLISION_MAX_RETRIES; suffix += 1) {
        occupyRunDir(root, `${base}_${suffix}`);
      }
    }

    await expect(runCli([
      "run",
      "--provider", "fake",
      "--workspace", workspace,
      "--root", root,
      "--plan", planName
    ])).rejects.toThrow(/run_id_collision_unresolved/);
  });

  test("explicit --run still throws run_id_already_exists on duplicate (no retry for explicit ids)", async () => {
    const workspace = initSourceCheckout("waygent-collision-explicit-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-collision-explicit-root-"));
    writeFileSync(join(workspace, "plan.md"), plan);
    occupyRunDir(root, "run_explicit_dup");

    await expect(runCli([
      "run",
      "--provider", "fake",
      "--workspace", workspace,
      "--root", root,
      "--run", "run_explicit_dup",
      "--plan", "plan.md"
    ])).rejects.toThrow(/run_id_already_exists/);
  });
});
