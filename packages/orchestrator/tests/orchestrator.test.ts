import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import { defaultRunRoot, runWaygentDemo } from "../src";
import { initSourceCheckout } from "./support/orchestratorFixtures";

describe("Waygent orchestrator", () => {
  test("keeps the default run root outside the source checkout", () => {
    expect(defaultRunRoot().startsWith(process.cwd())).toBe(false);
  });

  test("runs deterministic fake provider lifecycle", async () => {
    const result = await runWaygentDemo({
      root: mkdtempSync(join(tmpdir(), "waygent-run-")),
      workspace: initSourceCheckout("waygent-demo-source-")
    });
    expect(result.events).toHaveLength(16);
    expect(result.events.map((event) => event.event_type)).toContain("runway.preflight_result");
    expect(result.events.map((event) => event.event_type)).toContain("runway.checkpoint_created");
    expect(result.events.map((event) => event.event_type)).toContain("runway.apply_dry_run_result");
    expect(result.events.map((event) => event.event_type)).toContain("platform.cost_accumulated");
    expect(result.trust_report.trust_status).toBe("trusted");
    expect(result.projection.safe_wave).toEqual(["task_demo"]);
  });
});
