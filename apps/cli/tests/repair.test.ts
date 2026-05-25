import { describe, expect, test } from "bun:test";
import { repairRun } from "@waygent/orchestrator";

describe("waygent repair --dry-run", () => {
  test("returns packet without dispatching when run has no repairable task", async () => {
    const result = await repairRun({
      root: "/tmp/nonexistent",
      run: "missing_run",
      dry_run: true
    });
    expect(result.status).toBe("blocked");
    expect(result.reason).toBe("no_repairable_task");
  });
});
