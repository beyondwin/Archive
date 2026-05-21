import { describe, expect, test } from "bun:test";
import { rebuildRunSummary } from "../src";
import { demoEvent } from "../../lens-projectors/tests/support";

describe("projection rebuild", () => {
  test("falls back to filesystem events when cache is absent", () => {
    const summary = rebuildRunSummary([demoEvent({ sequence: 1 }), demoEvent({ sequence: 2, outcome: "failed" })]);
    expect(summary.failed_events).toBe(1);
    expect(summary.total_events).toBe(2);
  });
});
