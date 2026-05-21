import { describe, expect, test } from "bun:test";
import {
  buildConsoleUiModel,
  demoConsoleSnapshot,
  renderConsoleSnapshot
} from "../../apps/console/src/uiModel";

describe("Lens console browserless e2e model", () => {
  test("run list loads the demo run set", () => {
    const model = buildConsoleUiModel(demoConsoleSnapshot);

    expect(model.runs.map((run) => run.runId)).toEqual([
      "run_demo_trusted",
      "run_demo_failed",
      "run_demo_blocked"
    ]);
  });

  test("run detail exposes the three canonical event families required by the console", () => {
    const model = buildConsoleUiModel(demoConsoleSnapshot, "run_demo_trusted");

    expect(model.eventFamilies).toEqual(["platform", "runway", "lens"]);
  });

  test("trust report covers trusted, failed, and insufficient evidence states", () => {
    const verdicts = demoConsoleSnapshot.runs.map((run) => run.trust.verdict);

    expect(verdicts).toContain("trusted");
    expect(verdicts).toContain("failed");
    expect(verdicts).toContain("insufficient_evidence");
  });

  test("blocked runs expose a visible decision packet", () => {
    const snapshot = renderConsoleSnapshot(
      buildConsoleUiModel(demoConsoleSnapshot, "run_demo_blocked")
    );

    expect(snapshot).toContain("decision: task_verify verification_failed");
    expect(snapshot).toContain("allowed: rerun_verification, update_plan");
  });

  test("apply status is visible and blocks dirty source checkout application", () => {
    const model = buildConsoleUiModel(demoConsoleSnapshot, "run_demo_blocked");

    expect(model.selectedRun.applyStatus.dirtySourceCheckout).toBe(true);
    expect(model.selectedRun.applyStatus.canApply).toBe(false);
    expect(renderConsoleSnapshot(model)).toContain("apply: blocked dirty_source_checkout");
  });
});
