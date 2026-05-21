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
      tasks: [{ id: "task_demo", status: "verified" }],
      completion_audit: { status: "passed", commands: ["printf hello"] },
      apply: { status: "not_applied" }
    });
  });
});
