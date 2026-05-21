import { describe, expect, test } from "bun:test";
import { projectFailureSummary } from "../src";
import { demoEvent } from "./support";

describe("failure projector", () => {
  test("groups failures by task and class", () => {
    const summary = projectFailureSummary([
      demoEvent({ outcome: "failed", payload: { task_id: "task_demo", failure_class: "verification_failed" } })
    ]);
    expect(summary[0]?.failure_class).toBe("verification_failed");
    expect(summary[0]?.recovery_action).toBe("retry_with_evidence");
  });
});
