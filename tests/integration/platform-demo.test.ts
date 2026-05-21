import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import { runWaygentDemo } from "@waygent/orchestrator";

describe("platform demo", () => {
  test("prints a trusted run with three canonical events", async () => {
    const result = await runWaygentDemo({ root: mkdtempSync(join(tmpdir(), "waygent-platform-")) });
    expect(result.trust_report.trust_status).toBe("trusted");
    expect(result.summary.total_events).toBe(3);
    expect(result.timeline.map((entry) => entry.event_type)).toEqual([
      "platform.run_started",
      "runway.execution_profile_selected",
      "runway.verification_result"
    ]);
  });
});
