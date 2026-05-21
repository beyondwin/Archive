import { describe, expect, test } from "bun:test";
import { computeSafeWave, createTaskGraph } from "../src";

describe("safe-wave scheduler", () => {
  test("runs independent low and medium risk tasks together", () => {
    const graph = createTaskGraph([
      { id: "a", dependencies: [], file_claims: [{ path: "a", mode: "owned" }], resource_locks: [], risk: "low", status: "READY" },
      { id: "b", dependencies: [], file_claims: [{ path: "b", mode: "owned" }], resource_locks: [], risk: "medium", status: "READY" }
    ]);
    expect(computeSafeWave(graph).ready).toEqual(["a", "b"]);
  });

  test("serializes high risk tasks", () => {
    const graph = createTaskGraph([
      { id: "high", dependencies: [], file_claims: [{ path: "a", mode: "owned" }], resource_locks: [], risk: "high", status: "READY" },
      { id: "low", dependencies: [], file_claims: [{ path: "b", mode: "owned" }], resource_locks: [], risk: "low", status: "READY" }
    ]);
    expect(computeSafeWave(graph).ready).toEqual(["high"]);
  });
});
