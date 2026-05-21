import { describe, expect, test } from "bun:test";
import {
  buildConsoleUiModel,
  demoConsoleSnapshot,
  renderConsoleSnapshot
} from "./uiModel";

describe("Lens web console UI model", () => {
  test("builds run list and default detail sections", () => {
    const model = buildConsoleUiModel(demoConsoleSnapshot);

    expect(model.runs).toHaveLength(3);
    expect(model.selectedRun.runId).toBe("run_demo_trusted");
    expect(model.eventFamilies).toEqual(["platform", "runway", "lens"]);
    expect(model.sections.map((section) => section.id)).toEqual([
      "run-list",
      "run-detail",
      "task-timeline",
      "event-timeline",
      "trust-report",
      "failure-barriers",
      "decision-packets",
      "apply-status"
    ]);
  });

  test("exposes blocked decision packet and dirty apply status", () => {
    const model = buildConsoleUiModel(demoConsoleSnapshot, "run_demo_blocked");

    expect(model.selectedRun.trust.verdict).toBe("insufficient_evidence");
    expect(model.selectedRun.decisionPackets[0]).toMatchObject({
      taskId: "task_verify",
      failureClass: "verification_failed"
    });
    expect(model.selectedRun.applyStatus).toMatchObject({
      state: "blocked",
      dirtySourceCheckout: true
    });
  });

  test("renders a text snapshot for browserless e2e checks", () => {
    const snapshot = renderConsoleSnapshot(
      buildConsoleUiModel(demoConsoleSnapshot, "run_demo_failed")
    );

    expect(snapshot).toContain("run_demo_failed");
    expect(snapshot).toContain("failed");
    expect(snapshot).toContain("adapter_crashed");
    expect(snapshot).toContain("apply: not_ready");
  });
});
