import { describe, expect, test } from "bun:test";
import { projectFailureBarrierFromState } from "../src/failureBarrier";
import { stateFixture } from "./support";

describe("failure barrier projection", () => {
  test("maps verification failures to verification_fail barriers", () => {
    const state = stateFixture({
      status: "blocked",
      tasks: {
        task_demo: {
          status: "blocked",
          latest_failure_class: "verification_failed"
        }
      }
    });

    expect(projectFailureBarrierFromState(state)).toMatchObject({
      barrier_type: "verification_fail",
      task_id: "task_demo"
    });
  });

  test("maps budget pauses to budget_paused barriers", () => {
    const state = stateFixture({
      status: "blocked",
      apply: { status: "blocked", reason: "budget_paused" }
    });

    expect(projectFailureBarrierFromState(state)).toMatchObject({ barrier_type: "budget_paused" });
  });
});
