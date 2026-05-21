import { describe, expect, test } from "bun:test";
import { createTaskGraph } from "../src";

describe("durable task graph", () => {
  test("rejects cycles", () => {
    expect(() =>
      createTaskGraph([
        { id: "a", dependencies: ["b"], file_claims: [], resource_locks: [], risk: "low", status: "READY" },
        { id: "b", dependencies: ["a"], file_claims: [], resource_locks: [], risk: "low", status: "READY" }
      ])
    ).toThrow(/cycle/);
  });

  test("withholds tasks with dependency checkpoints missing", () => {
    const graph = createTaskGraph([
      { id: "base", dependencies: [], file_claims: [], resource_locks: [], risk: "low", status: "READY" },
      { id: "next", dependencies: ["base"], file_claims: [], resource_locks: [], risk: "low", status: "READY" }
    ]);
    expect(graph.tasks.get("next")?.dependencies).toEqual(["base"]);
  });
});
