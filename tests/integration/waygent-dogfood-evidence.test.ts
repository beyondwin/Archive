import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runWaygentDogfoodCheck } from "../../packages/testkit/src";

describe("Waygent dogfood evidence gate", () => {
  test("offline fake-provider dogfood run has complete maturity evidence", async () => {
    const check = await runWaygentDogfoodCheck({
      root: mkdtempSync(join(tmpdir(), "waygent-dogfood-root-"))
    });

    expect(check.status).toBe("passed");
    expect(check.failed_checks).toEqual([]);
    expect(check.maturity.dogfood_evidence.status).toBe("complete");
    expect(check.maturity.runtime_cost.measured_wave_count).toBeGreaterThanOrEqual(1);
    expect(check.maturity.provider_readiness.status).toBe("ready");
    expect(check.explain.summary).not.toContain("unknown");
  });
});
