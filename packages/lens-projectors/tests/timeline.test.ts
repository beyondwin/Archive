import { describe, expect, test } from "bun:test";
import { projectTimeline } from "../src";
import { demoEvent } from "./support";

describe("timeline projector", () => {
  test("orders events by sequence", () => {
    expect(
      projectTimeline([
        demoEvent({ sequence: 2, event_type: "kernel.exec_completed" }),
        demoEvent({ sequence: 1, event_type: "platform.run_started" })
      ]).map((event) => event.event_type)
    ).toEqual(["platform.run_started", "kernel.exec_completed"]);
  });
});
