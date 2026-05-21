import { describe, expect, test } from "bun:test";
import {
  buildRunDetailModel,
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

  test("real run detail model exposes v2 operator evidence sections", () => {
    const detail = buildRunDetailModel({
      run_id: "run_e2e_v2",
      status: "blocked",
      trust_status: "insufficient_evidence",
      apply_status: "blocked",
      total_events: 3,
      last_event_type: "runway.recovery_decision_created",
      safe_wave: [],
      failures: [{ task_id: "task_e2e", failure_class: "verification_failed", count: 1 }],
      timeline: [
        { sequence: 1, phase: "platform", event_type: "platform.run_started", outcome: "running", summary: "Run opened." },
        { sequence: 3, phase: "runway", event_type: "runway.recovery_decision_created", outcome: "blocked", summary: "Recovery decision created." }
      ],
      provider_attempts: [{ attempt_id: "attempt_task_e2e_1", task_id: "task_e2e", provider: "codex" }],
      verification: [{ verification_id: "verify_task_e2e_1", task_id: "task_e2e", status: "failed" }],
      reviews: [{ task_id: "task_e2e", verdict: "needs_fix" }],
      recovery: [{ task_id: "task_e2e", recommended_next_action: "rerun_verification" }],
      drift: { last_checked_at: null, records: [], unrepaired_blockers: [] }
    });

    expect(detail.sections.map((section) => section.id)).toContain("provider-attempts");
    expect(detail.sections.map((section) => section.id)).toContain("verification-evidence");
    expect((detail as any).provider_attempts[0]).toMatchObject({
      attempt_id: "attempt_task_e2e_1"
    });
  });
});
