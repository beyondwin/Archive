import { mkdtempSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import { runWaygentDemo } from "@waygent/orchestrator";

describe("platform demo", () => {
  test("prints a trusted run with durable canonical events", async () => {
    const result = await runWaygentDemo({
      root: mkdtempSync(join(tmpdir(), "waygent-platform-")),
      workspace: initSourceCheckout("waygent-platform-source-")
    });
    expect(result.trust_report.trust_status).toBe("trusted");
    expect(result.summary.total_events).toBe(9);
    expect(result.timeline.map((entry) => entry.event_type)).toEqual([
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
  });

  test("CLI demo is isolated from the caller checkout dirtiness", () => {
    const repoRoot = join(import.meta.dir, "..", "..");
    const result = Bun.spawnSync(["bun", "run", "apps/cli/src/demo.ts"], { cwd: repoRoot });
    expect(result.exitCode).toBe(0);
    expect(JSON.parse(result.stdout.toString())).toMatchObject({
      trust_status: "trusted",
      total_events: 9,
      apply_state: "not_applied"
    });
  });
});

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
