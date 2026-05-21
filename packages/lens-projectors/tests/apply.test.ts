import { describe, expect, test } from "bun:test";
import { projectApplyState } from "../src/apply";
import { demoEvent } from "./support";

describe("apply projector", () => {
  test("reports verified but unapplied runs as apply-ready", () => {
    expect(projectApplyState([demoEvent({ event_type: "runway.verification_result", outcome: "success" })])).toEqual({
      status: "ready",
      reason: null
    });
  });

  test("reports dirty source checkout as blocked", () => {
    expect(
      projectApplyState([
        demoEvent({
          event_type: "runway.apply_blocked",
          outcome: "blocked",
          summary: "Dirty source checkout.",
          payload: { reason: "dirty_source_checkout" }
        })
      ])
    ).toEqual({
      status: "blocked",
      reason: "dirty_source_checkout"
    });
  });
});
