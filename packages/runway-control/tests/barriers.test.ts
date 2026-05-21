import { describe, expect, test } from "bun:test";
import { buildDurableProjection, computeSafeWave, createTaskGraph } from "../src";

describe("scheduler barriers", () => {
  test("serializes overlapping owned claims", () => {
    const graph = createTaskGraph([
      { id: "a", dependencies: [], file_claims: [{ path: "packages/contracts", mode: "owned" }], resource_locks: [], risk: "low", status: "READY" },
      { id: "b", dependencies: [], file_claims: [{ path: "packages/contracts/src", mode: "owned" }], resource_locks: [], risk: "low", status: "READY" }
    ]);
    const wave = computeSafeWave(graph);
    expect(wave.ready).toEqual(["a"]);
    expect(wave.withheld[0]?.reason).toBe("file_claim");
  });

  test("blocks stale activities and terminal failures", () => {
    const graph = createTaskGraph([
      { id: "stale", dependencies: [], file_claims: [], resource_locks: [], risk: "low", status: "READY", stale: true },
      { id: "failed", dependencies: [], file_claims: [], resource_locks: [], risk: "low", status: "READY", latest_failure_class: "terminal_rejected" }
    ]);
    const projection = buildDurableProjection(graph);
    expect(projection.safe_wave).toEqual([]);
    expect(projection.required_human_decision?.failure_class).toBe("terminal_rejected");
  });
});
