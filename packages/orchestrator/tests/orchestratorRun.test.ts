import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readLatestRunId } from "@waygent/lens-store";
import { runWaygent } from "../src/orchestrator";
import { readRunStateV2 } from "../src/runState";

const plan = `
\`\`\`yaml waygent-task
id: task_demo
title: Demo task
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
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "before\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
  return workspace;
}

describe("runWaygent", () => {
  test("runs a parsed plan through fake provider and durable events", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-"));
    const workspace = initSourceCheckout("waygent-run-source-");
    const result = await runWaygent({ root, workspace, run_id: "run_demo", plan, profile: { provider: "fake", execution_mode: "multi-agent" } });

    expect(readLatestRunId(root)).toBe("run_demo");
    expect(result.events.map((event) => event.event_type)).toEqual([
      "platform.run_started",
      "runway.plan_loaded",
      "runway.preflight_result",
      "runway.safe_wave_selected",
      "runway.worker_result",
      "runway.verification_result",
      "runway.checkpoint_created",
      "runway.apply_dry_run_result",
      "lens.trust_report_updated"
    ]);
    expect(result.trust_report.trust_status).toBe("trusted");
    expect(result.projection.safe_wave).toEqual(["task_demo"]);
    expect(readRunStateV2(root, "run_demo")).toMatchObject({
      schema: "waygent.run_state.v2",
      status: "completed",
      worktree_root: join(root, "worktrees"),
      tasks: { task_demo: { id: "task_demo", status: "verified" } },
      completion_audit: { status: "passed", required_checks: ["printf hello"] },
      apply: { status: "not_applied" }
    });
  });

  test("dispatches every task in the scheduler-approved safe wave", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-safe-wave-"));
    const workspace = initSourceCheckout("waygent-safe-wave-source-");
    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_wave",
      profile: { provider: "fake", execution_mode: "multi-agent" },
      plan: `
\`\`\`yaml waygent-task
id: task_a
title: Task A
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: low
verify:
  - printf a
\`\`\`
\`\`\`yaml waygent-task
id: task_b
title: Task B
dependencies: []
file_claims:
  - path: b.txt
    mode: owned
risk: low
verify:
  - printf b
\`\`\`
`
    });

    expect(result.projection.safe_wave).toEqual(["task_a", "task_b"]);
    expect(result.events.filter((event) => event.event_type === "runway.worker_result")).toHaveLength(2);
  });

  test("continues to dependent tasks after dependency checkpoint exists", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-dependent-wave-"));
    const workspace = initSourceCheckout("waygent-dependent-wave-source-");
    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_dependent_wave",
      profile: { provider: "fake", execution_mode: "multi-agent" },
      plan: `
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
`
    });

    expect(result.events.filter((event) => event.event_type === "runway.worker_result")).toHaveLength(2);
    expect(readRunStateV2(root, "run_dependent_wave").tasks.task_followup?.status).toBe("verified");
  });

  test("uses the selected process provider instead of the fake provider", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-codex-provider-"));
    const script = `
      const prompt = await new Response(Bun.stdin.stream()).text();
      console.log(JSON.stringify({
        summary: "selected codex " + prompt.includes("Demo task"),
        evidence: { prompt_length: prompt.length }
      }));
    `;

    const result = await runWaygent({
      root,
      workspace: initSourceCheckout("waygent-codex-provider-source-"),
      run_id: "run_codex",
      plan,
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: { codex: { executable: process.execPath, args: ["-e", script] } }
    });

    const workerEvent = result.events.find((event) => event.event_type === "runway.worker_result");
    const worker = (workerEvent?.payload.worker ?? {}) as { summary?: string; evidence?: Record<string, unknown> };
    expect(worker.summary).toBe("selected codex true");
    expect(worker.evidence).toMatchObject({ provider: "codex" });
    expect(readRunStateV2(root, "run_codex").provider_profile.provider).toBe("codex");
  });
});
