import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runWaygent } from "../src/orchestrator";
import { applyRun, resumeRun } from "../src/runCommands";
import { readRunStateV2 } from "../src/runState";

function initSourceCheckout(): string {
  const workspace = mkdtempSync(join(tmpdir(), "waygent-apply-e2e-source-"));
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "before\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
  return workspace;
}

const plan = `
\`\`\`yaml waygent-task
id: task_apply_ready
title: Update README through fake provider
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - test -f README.md
\`\`\`
`;

describe("Waygent run to apply E2E", () => {
  test("a completed run exposes and applies a real verified checkpoint", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-apply-e2e-root-"));
    const workspace = initSourceCheckout();

    await runWaygent({
      root,
      workspace,
      run_id: "run_apply_ready",
      plan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_apply_ready");
    expect(state.status).toBe("completed");
    expect(resumeRun({ root, run: "run_apply_ready", dry_run: true }).allowed_actions).toContain(
      "apply_verified_checkpoint"
    );
    expect(await applyRun({ root, run: "run_apply_ready", workspace })).toMatchObject({
      command: "apply",
      run_id: "run_apply_ready",
      status: "applied"
    });
  });

  test("a run with no checkpoint artifact is blocked before completion", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-no-checkpoint-root-"));
    const workspace = initSourceCheckout();
    const noWritePlan = `
\`\`\`yaml waygent-task
id: task_no_checkpoint
title: No checkpoint task
dependencies: []
file_claims:
  - path: README.md
    mode: read_only
risk: low
verify:
  - test -f README.md
\`\`\`
`;

    await runWaygent({
      root,
      workspace,
      run_id: "run_no_checkpoint",
      plan: noWritePlan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_no_checkpoint");
    expect(state.status).toBe("blocked");
    expect(state.lifecycle_outcome).toBe("blocked");
    expect(state.completion_audit).toMatchObject({ status: "failed" });
    expect(resumeRun({ root, run: "run_no_checkpoint", dry_run: true }).allowed_actions).toEqual([
      "retry_checkpoint_generation"
    ]);
  });

  test("a verified no-op run remains apply-ready and applies without a patch mutation", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-noop-apply-root-"));
    const workspace = initSourceCheckout();
    const noOpPlan = `
\`\`\`yaml waygent-task
id: task_noop_apply
title: Verify already-present README content
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - grep before README.md
\`\`\`
`;
    const script = `
      await new Response(Bun.stdin.stream()).text();
      console.log(JSON.stringify({
        status: "completed",
        summary: "nothing to change",
        changed_files: [],
        evidence: { no_op: true }
      }));
    `;

    await runWaygent({
      root,
      workspace,
      run_id: "run_noop_apply",
      plan: noOpPlan,
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: { codex: { executable: process.execPath, args: ["-e", script] } }
    });

    const state = readRunStateV2(root, "run_noop_apply");
    expect(state.status).toBe("completed");
    expect(state.completion_audit).toMatchObject({
      status: "passed",
      combined_apply_evidence: { status: "passed", patch_byte_length: 0, no_op: true }
    });
    expect(resumeRun({ root, run: "run_noop_apply", dry_run: true }).allowed_actions).toContain(
      "apply_verified_checkpoint"
    );
    expect(await applyRun({ root, run: "run_noop_apply", workspace })).toMatchObject({
      command: "apply",
      run_id: "run_noop_apply",
      status: "applied"
    });
    expect(readFileSync(join(workspace, "README.md"), "utf8")).toBe("before\n");
  });

  test("apply materializes every verified checkpoint in a completed run", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-apply-multi-root-"));
    const workspace = initSourceCheckout();
    const multiTaskPlan = `
\`\`\`yaml waygent-task
id: task_base
title: Base task
dependencies: []
file_claims:
  - path: base.txt
    mode: owned
risk: low
verify:
  - test -f base.txt
\`\`\`
\`\`\`yaml waygent-task
id: task_followup
title: Followup task
dependencies: [task_base]
file_claims:
  - path: followup.txt
    mode: owned
risk: low
verify:
  - test -f followup.txt
\`\`\`
`;

    await runWaygent({
      root,
      workspace,
      run_id: "run_apply_multi",
      plan: multiTaskPlan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    expect(await applyRun({ root, run: "run_apply_multi", workspace })).toMatchObject({
      command: "apply",
      run_id: "run_apply_multi",
      status: "applied"
    });
    expect(readFileSync(join(workspace, "base.txt"), "utf8")).toContain("task_base");
    expect(readFileSync(join(workspace, "followup.txt"), "utf8")).toContain("task_followup");
  });

  test("apply uses a materialized final patch for sequential checkpoints touching the same file", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-apply-overlap-root-"));
    const workspace = initSourceCheckout();
    const overlappingPlan = `
\`\`\`yaml waygent-task
id: task_first
title: First shared file update
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - grep task_first README.md
\`\`\`
\`\`\`yaml waygent-task
id: task_second
title: Second shared file update
dependencies: [task_first]
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - grep task_second README.md
\`\`\`
`;

    await runWaygent({
      root,
      workspace,
      run_id: "run_apply_overlap",
      plan: overlappingPlan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_apply_overlap");
    expect(state.status).toBe("completed");
    expect(resumeRun({ root, run: "run_apply_overlap", dry_run: true }).allowed_actions).toContain(
      "apply_verified_checkpoint"
    );
    expect(await applyRun({ root, run: "run_apply_overlap", workspace })).toMatchObject({
      command: "apply",
      run_id: "run_apply_overlap",
      status: "applied"
    });
    expect(readFileSync(join(workspace, "README.md"), "utf8")).toContain("task_second");
  });
});
