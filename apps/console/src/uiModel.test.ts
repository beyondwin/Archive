import { describe, expect, test } from "bun:test";
import {
  buildRunDetailModel,
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

  test("builds detail sections from a real Waygent run API response", () => {
    const model = buildRunDetailModel({
      run_id: "run_real",
      status: "completed",
      trust_status: "trusted",
      apply_status: "ready",
      total_events: 6,
      last_event_type: "lens.trust_report_updated",
      safe_wave: ["task_real"],
      failures: [],
      timeline: [
        { sequence: 1, phase: "platform", event_type: "platform.run_started", outcome: "running", summary: "Run opened." },
        { sequence: 6, phase: "lens", event_type: "lens.trust_report_updated", outcome: "success", summary: "Trust report updated." }
      ]
    });

    expect(model.header).toMatchObject({
      run_id: "run_real",
      status: "completed",
      trust_status: "trusted",
      apply_status: "ready"
    });
    expect(model.sections.map((section) => section.id)).toContain("safe-wave");
  });
});
