import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readLatestRunId } from "@waygent/lens-store";
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
    expect(state.preflight).toMatchObject({ status: "clean", reason: null, decision_packet_ref: null });
    expect(readLatestRunId(root)).toBe("run_v2");
  });

  test("blocks dirty related source checkout before provider dispatch", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-dirty-related-source-");
    writeFileSync(join(workspace, "a.txt"), "dirty source evidence\n");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-dirty-related-"));

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_dirty_related",
      plan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_dirty_related");
    expect(state).toMatchObject({
      status: "blocked",
      lifecycle_outcome: "blocked",
      current_phase: "preflight",
      apply: { status: "blocked", reason: "dirty_source_checkout" },
      preflight: {
        status: "dirty_related",
        dirty_files: ["a.txt"],
        related: ["a.txt"],
        reason: "dirty_source_checkout",
        decision_packet_ref: null
      }
    });
    expect(state.provider_attempts).toEqual([]);
    expect(result.events.find((event) => event.event_type === "runway.preflight_result")).toMatchObject({
      outcome: "blocked",
      payload: { status: "dirty_related", reason: "dirty_source_checkout" }
    });
    expect(result.events.some((event) => event.event_type === "runway.worker_result")).toBe(false);
    expect(readLatestRunId(root)).toBe("run_dirty_related");
  });

  test("records dirty unrelated preflight warning and proceeds", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-dirty-unrelated-source-");
    writeFileSync(join(workspace, "notes.md"), "operator note\n");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-dirty-unrelated-"));

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_dirty_unrelated",
      plan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_dirty_unrelated");
    expect(state.status).toBe("completed");
    expect(state.provider_attempts).toHaveLength(1);
    expect(state.preflight).toMatchObject({
      status: "dirty_unrelated",
      dirty_files: ["notes.md"],
      related: [],
      unrelated: ["notes.md"],
      reason: "dirty_unrelated_source_checkout",
      decision_packet_ref: null
    });
    expect(result.events.find((event) => event.event_type === "runway.preflight_result")).toMatchObject({
      outcome: "success",
      severity: "warning",
      payload: { status: "dirty_unrelated", reason: "dirty_unrelated_source_checkout" }
    });
  });

  test("refuses to overwrite existing run evidence for a duplicate run id", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-duplicate-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-duplicate-"));
    const runRoot = join(root, "run_duplicate");
    mkdirSync(runRoot, { recursive: true });
    const eventJournal = join(runRoot, "events.jsonl");
    writeFileSync(eventJournal, "existing evidence\n");

    await expect(runWaygent({
      root,
      workspace,
      run_id: "run_duplicate",
      plan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    })).rejects.toThrow("run_id_already_exists");

    expect(existsSync(runRoot)).toBe(true);
    expect(readFileSync(eventJournal, "utf8")).toBe("existing evidence\n");
  });
});

function initSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "fixture\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
  return workspace;
}
