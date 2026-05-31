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
      "platform.intake_extract_completed",
      "platform.plan_preflight_completed",
      "runway.plan_loaded",
      "runway.preflight_result",
      "runway.safe_wave_selected",
      "runway.spec_slice_computed",
      "context.packet_budget_evaluated",
      "handoff.created",
      "runway.worker_result",
      "lens.model_attestation_confirmed",
      "runway.verification_result",
      "runway.checkpoint_created",
      "runway.apply_dry_run_result",
      "platform.cost_accumulated",
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

  test("continues after repair budget state is persisted", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-repair-budget-"));
    const workspace = initSourceCheckout("waygent-repair-budget-source-");
    const counterPath = join(root, "counter.txt");
    const script = `
      const fs = require("node:fs");
      const path = require("node:path");
      const prompt = fs.readFileSync(0, "utf8");
      const counterPath = process.env.WAYGENT_TEST_COUNTER;
      const previous = fs.existsSync(counterPath) ? Number(fs.readFileSync(counterPath, "utf8")) : 0;
      const next = previous + 1;
      fs.writeFileSync(counterPath, String(next));
      const isRepair = prompt.includes("role: fix") || prompt.includes("Repair task:");
      if (isRepair || next > 2) {
        fs.writeFileSync(path.join(process.cwd(), "fixed.txt"), "fixed\\n");
      } else {
        fs.writeFileSync(path.join(process.cwd(), "README.md"), "broken\\n");
      }
      console.log(JSON.stringify({
        status: "completed",
        changed_files: isRepair || next > 2 ? ["README.md", "fixed.txt"] : ["README.md"],
        summary: isRepair ? "repair wrote fixed file" : "implement attempt " + next,
        evidence: { attempt: next, role: isRepair ? "fix" : "implement" }
      }));
    `;

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_repair_budget",
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: {
        codex: {
          executable: process.execPath,
          args: ["-e", script],
          env: { WAYGENT_TEST_COUNTER: counterPath }
        }
      },
      plan: `
\`\`\`yaml waygent-task
id: task_repair
title: Repair then retry
dependencies: []
file_claims:
  - path: README.md
    mode: owned
  - path: fixed.txt
    mode: owned
risk: low
verify:
  - test -f fixed.txt
\`\`\`
`
    });

    const state = readRunStateV2(root, "run_repair_budget");
    expect(result.events.map((event) => event.event_type)).toContain("runway.repair_result");
    expect(state.repair_budget?.task_repair).toEqual({ max_attempts: 2, current: 1 });
    expect(state.status).toBe("completed");
    expect(state.tasks.task_repair?.status).toBe("verified");
  });

  test("records salvage evidence for malformed provider output with captured patch", async () => {
    const workspace = initSourceCheckout("waygent-salvage-malformed-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-salvage-malformed-root-"));
    const script = join(workspace, "malformed-provider.mjs");
    writeFileSync(script, [
      "import { writeFileSync } from 'node:fs';",
      "writeFileSync('salvage.txt', 'salvaged\\n');",
      "process.stdout.write('{not json');"
    ].join("\n"));

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_salvage_malformed",
      plan: "```yaml waygent-task\nid: task_salvage\ntitle: Salvage malformed provider\ndependencies: []\nfile_claims:\n  - path: salvage.txt\n    mode: owned\nrisk: low\nverify:\n  - test -f salvage.txt\n```",
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: {
        codex: {
          executable: process.execPath,
          args: [script]
        }
      }
    });

    const state = readRunStateV2(root, "run_salvage_malformed");
    expect(result.events.map((event) => event.event_type)).toContain("runway.patch_salvaged");
    expect(state.recovery).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          task_id: "task_salvage",
          action: "salvage_then_review",
          result: "scheduled",
          salvage_ref: "artifacts/salvage/task_salvage/attempt_task_salvage_1.json"
        })
      ])
    );
    expect(state.apply.status).toBe("blocked");
    expect(state.completion_audit?.status).toBe("failed");
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
