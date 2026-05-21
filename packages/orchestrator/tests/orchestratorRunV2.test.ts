import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runWaygent } from "../src/orchestrator";
import { readRunStateV2 } from "../src/runState";

const plan = `
\`\`\`yaml waygent-task
id: task_a
title: Create file A
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: low
verify:
  - test -f a.txt
\`\`\`
`;

describe("runWaygent v2 lifecycle", () => {
  test("creates v2 state, task packet, real verification evidence, and completion audit", async () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-run-v2-workspace-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "fixture\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-"));

    await runWaygent({
      root,
      workspace,
      run_id: "run_v2",
      plan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_v2");
    expect(state.schema).toBe("waygent.run_state.v2");
    expect(state.tasks.task_a?.task_packet_path).toBeTruthy();
    expect(state.tasks.task_a?.checkpoint_refs[0]).toContain("artifacts/checkpoints/task_a/candidate_task_a.json");
    expect(state.provider_attempts).toHaveLength(1);
    expect(state.verification.length).toBeGreaterThan(0);
    expect(state.completion_audit).toMatchObject({
      status: "passed",
      checkpoint_evidence: [expect.objectContaining({ ok: true })]
    });
  });
});
