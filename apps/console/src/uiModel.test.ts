import { describe, expect, test } from "bun:test";
import {
  buildRunDetailModel,
  buildConsoleUiModel,
  demoConsoleSnapshot,
  realRunDetailToConsoleRun,
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

  test("builds v2 evidence sections from a real Waygent run API response", () => {
    const model = buildRunDetailModel({
      run_id: "run_real_v2",
      status: "blocked",
      trust_status: "insufficient_evidence",
      apply_status: "blocked",
      total_events: 8,
      last_event_type: "runway.decision_packet_created",
      safe_wave: [],
      failures: [{ task_id: "task_demo", failure_class: "verification_failed", count: 1 }],
      timeline: [
        { sequence: 1, phase: "platform", event_type: "platform.run_started", outcome: "running", summary: "Run opened." },
        { sequence: 8, phase: "runway", event_type: "runway.decision_packet_created", outcome: "blocked", summary: "Decision required." }
      ],
      provider_attempts: [
        {
          attempt_id: "attempt_task_demo_1",
          task_id: "task_demo",
          role: "implement",
          provider: "codex",
          exit_code: 0,
          timed_out: false
        }
      ],
      verification: [
        {
          verification_id: "verify_task_demo_1",
          task_id: "task_demo",
          command: "bun test",
          status: "failed"
        }
      ],
      reviews: [
        {
          task_id: "task_demo",
          verdict: "needs_fix",
          findings: [{ severity: "important", summary: "Needs verification evidence." }],
          residual_risk: ["verification incomplete"]
        }
      ],
      recovery: [
        {
          task_id: "task_demo",
          failure_class: "verification_failed",
          recommended_next_action: "rerun_verification"
        }
      ],
      drift: {
        last_checked_at: "2026-05-21T00:02:00.000Z",
        records: [{ status: "checked" }],
        unrepaired_blockers: [{ failure_class: "state_drift" }]
      }
    });

    expect(model.sections.map((section) => section.id)).toEqual([
      "overview",
      "safe-wave",
      "timeline",
      "trust-failure",
      "apply-state",
      "provider-attempts",
      "verification-evidence",
      "review-findings",
      "recovery-decisions",
      "drift"
    ]);
    expect((model as any).provider_attempts[0]).toMatchObject({
      attempt_id: "attempt_task_demo_1",
      provider: "codex"
    });
    expect((model as any).verification[0]).toMatchObject({
      verification_id: "verify_task_demo_1",
      status: "failed"
    });
    expect((model as any).reviews[0]).toMatchObject({
      verdict: "needs_fix"
    });
    expect((model as any).recovery[0]).toMatchObject({
      recommended_next_action: "rerun_verification"
    });
    expect((model as any).drift.unrepaired_blockers[0]).toMatchObject({
      failure_class: "state_drift"
    });
  });

  test("maps v2 apply readiness evidence into console apply status", () => {
    expect(realRunDetailToConsoleRun({
      run_id: "run_blocked",
      status: "blocked",
      trust_status: "insufficient_evidence",
      apply_status: "blocked",
      total_events: 1,
      last_event_type: "runway.apply_blocked",
      safe_wave: [],
      failures: [],
      timeline: [],
      apply_readiness: {
        status: "blocked",
        reason: "state_drift",
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        combined_patch_ref: null,
        source: "run_state_v2"
      },
      drift: {
        last_checked_at: "2026-05-21T00:00:00Z",
        records: [],
        unrepaired_blockers: [{ failure_class: "state_drift" }]
      }
    }).applyStatus).toMatchObject({
      state: "blocked",
      canApply: false,
      reason: "state_drift",
      checkpointRef: "artifacts/checkpoints/task_a/candidate_task_a.json",
      combinedPatchRef: null
    });
  });
});
