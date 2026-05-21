import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import { runWaygentDemo } from "../src";

describe("Waygent orchestrator", () => {
  test("runs deterministic fake provider lifecycle", async () => {
    const result = await runWaygentDemo({ root: mkdtempSync(join(tmpdir(), "waygent-run-")) });
    expect(result.events).toHaveLength(8);
    expect(result.events.map((event) => event.event_type)).toContain("runway.checkpoint_created");
    expect(result.events.map((event) => event.event_type)).toContain("runway.apply_dry_run_result");
    expect(result.trust_report.trust_status).toBe("trusted");
    expect(result.projection.safe_wave).toEqual(["task_demo"]);
  });
});
