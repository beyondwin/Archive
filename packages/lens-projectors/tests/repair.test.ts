import { describe, expect, test } from "bun:test";
import { projectTimeline } from "../src/timeline";
import { demoEvent } from "./support";

describe("timeline includes repair events", () => {
  test("repair_dispatched and repair_result surface with phase=repair", () => {
    const events = [
      demoEvent({
        sequence: 1,
        event_type: "runway.repair_dispatched",
        phase: "repair",
        outcome: "success",
        summary: "Repair worker dispatched."
      }),
      demoEvent({
        sequence: 2,
        event_type: "runway.repair_result",
        phase: "repair",
        outcome: "success",
        summary: "Repair worker completed."
      })
    ];
    const timeline = projectTimeline(events);
    expect(timeline.some((entry) => entry.event_type === "runway.repair_dispatched")).toBe(true);
    expect(timeline.some((entry) => entry.event_type === "runway.repair_result")).toBe(true);
    const repairEntries = timeline.filter((entry) => entry.phase === "repair");
    expect(repairEntries.length).toBe(2);
  });
});
