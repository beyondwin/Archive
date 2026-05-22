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
      "run_demo_blocked",
      "run_demo_failed",
      "run_demo_trusted"
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

  test("real run detail model exposes Workbench operator decision sections", () => {
    const detail = buildRunDetailModel({
      run_id: "run_workbench_e2e",
      status: "blocked",
      trust_status: "insufficient_evidence",
      apply_status: "blocked",
      total_events: 2,
      last_event_type: "runway.verification_result",
      safe_wave: [],
      failures: [],
      timeline: [
        { sequence: 1, phase: "platform", event_type: "platform.run_started", outcome: "running", summary: "Run opened." },
        { sequence: 2, phase: "runway", event_type: "runway.verification_result", outcome: "failed", summary: "Verification failed." }
      ],
      operator_decision: {
        schema: "waygent.operator_decision.v1",
        run_id: "run_workbench_e2e",
        generated_at: "2026-05-22T00:00:00.000Z",
        status_summary: {
          display_status: "blocked",
          runtime_status: "blocked",
          lifecycle_outcome: "blocked",
          current_phase: "recover",
          active_tasks: 0,
          completed_tasks: 0,
          blocked_tasks: 1,
          apply_status: "blocked",
          summary: "run_workbench_e2e is blocked by verification_failed."
        },
        primary_blocker: {
          code: "verification_failed",
          title: "Verification failed",
          summary: "task_e2e failed verification.",
          severity: "blocking",
          task_id: "task_e2e",
          evidence_refs: ["verification:task_e2e"],
          missing_refs: [],
          recommended_action_ids: ["rerun_verification"]
        },
        secondary_blockers: [],
        allowed_actions: [
          { id: "inspect_run", label: "Inspect run", reason: "safe", evidence_refs: ["state:state.json"], requires_approval: false, requires_runtime_revalidation: false, command: "waygent inspect --run run_workbench_e2e" }
        ],
        blocked_actions: [
          { id: "apply_run", label: "Apply run", reason: "Apply readiness is blocked by verification_failed.", evidence_refs: ["verification:task_e2e"], unblocks_when: "Verification passes." }
        ],
        evidence_packet: {
          state_refs: ["state:state.json"],
          event_refs: ["events:events.jsonl"],
          artifact_refs: [],
          verification_refs: ["verification:task_e2e"],
          checkpoint_refs: [],
          projection_refs: [],
          missing_refs: [],
          redaction_notes: []
        },
        ai_handoff: {
          purpose: "draft_repair_plan",
          prompt_summary: "Draft a repair plan from bounded evidence.",
          run_id: "run_workbench_e2e",
          current_status: "blocked",
          primary_blocker: "verification_failed",
          secondary_blockers: [],
          allowed_action_ids: ["inspect_run"],
          blocked_action_ids: ["apply_run"],
          constraints: ["Do not apply patches."],
          evidence_refs: ["verification:task_e2e"],
          missing_evidence: [],
          raw_fallback_refs: ["events:events.jsonl"],
          safety_notes: ["Waygent runtime remains apply authority."]
        },
        confidence: "deterministic",
        unknown_reasons: [],
        source_projection_refs: {
          run_state_v2: "state:state.json",
          apply_readiness: "waygent.apply_readiness",
          execution_explanation: null,
          operational_maturity: null
        }
      }
    });

    expect(detail.outcome_strip).toMatchObject({
      display_status: "blocked",
      primary_blocker: "verification_failed",
      next_action: "inspect_run"
    });
    expect(detail.operator_timeline.map((row) => row.row_type)).toEqual(["raw_event", "verification_result"]);
    expect(detail.sections.map((section) => section.id)).toEqual(expect.arrayContaining([
      "operator-decision",
      "operator-timeline",
      "ai-handoff",
      "raw-evidence"
    ]));
    expect(detail.raw_evidence_refs).toEqual(["state:state.json", "events:events.jsonl"]);
  });
});
