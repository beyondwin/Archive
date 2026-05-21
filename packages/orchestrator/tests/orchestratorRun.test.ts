import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readLatestRunId } from "@waygent/lens-store";
import { runWaygent } from "../src/orchestrator";
import { readRunState } from "../src/runState";

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

describe("runWaygent", () => {
  test("runs a parsed plan through fake provider and durable events", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-"));
    const result = await runWaygent({ root, run_id: "run_demo", plan, profile: { provider: "fake", execution_mode: "multi-agent" } });

    expect(readLatestRunId(root)).toBe("run_demo");
    expect(result.events.map((event) => event.event_type)).toEqual([
      "platform.run_started",
      "runway.plan_loaded",
      "runway.safe_wave_selected",
      "runway.worker_result",
      "runway.verification_result",
      "lens.trust_report_updated"
    ]);
    expect(result.trust_report.trust_status).toBe("trusted");
    expect(result.projection.safe_wave).toEqual(["task_demo"]);
    expect(readRunState(root, "run_demo")).toMatchObject({
      status: "completed",
      worktree: join(root, "worktrees", "run_demo", "task_demo"),
      tasks: [{ id: "task_demo", status: "verified" }],
      completion_audit: { status: "passed", commands: ["printf hello"] },
      apply: { status: "not_applied" }
    });
  });

  test("dispatches every task in the scheduler-approved safe wave", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-safe-wave-"));
    const result = await runWaygent({
      root,
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
      run_id: "run_codex",
      plan,
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: { codex: { executable: process.execPath, args: ["-e", script] } }
    });

    const workerEvent = result.events.find((event) => event.event_type === "runway.worker_result");
    const worker = (workerEvent?.payload.worker ?? {}) as { summary?: string; evidence?: Record<string, unknown> };
    expect(worker.summary).toBe("selected codex true");
    expect(worker.evidence).toMatchObject({ provider: "codex" });
    expect(readRunState(root, "run_codex").provider).toBe("codex");
  });
});
