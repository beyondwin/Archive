import { describe, expect, test } from "bun:test";
import {
  buildRunDetailModel,
  buildConsoleUiModel,
  demoConsoleSnapshot,
  realRunSummaryToConsoleRun,
  realRunDetailToConsoleRun,
  renderConsoleSnapshot
} from "./uiModel";

describe("Lens web console UI model", () => {
  test("builds run list and default detail sections", () => {
    const model = buildConsoleUiModel(demoConsoleSnapshot);

    expect(model.runs).toHaveLength(3);
    expect(model.selectedRun.runId).toBe("run_demo_blocked");
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

  test("renders blocked Workbench decision text for browserless checks", () => {
    const snapshot = renderConsoleSnapshot(
      buildConsoleUiModel(demoConsoleSnapshot, "run_demo_blocked")
    );

    expect(snapshot).toContain("run_demo_blocked");
    expect(snapshot).toContain("decision:");
    expect(snapshot).toContain("verification_failed");
    expect(snapshot).toContain("allowed: rerun_verification, update_plan");
    expect(snapshot).toContain("apply: blocked dirty_source_checkout");
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
          timed_out: false,
          process: {
            stderr_summary: {
              total_lines: 2,
              counts: { error: 0, warning: 1, mcp: 0, plugin_manifest: 1, skill_loader: 0, other: 0 },
              samples: [{ category: "plugin_manifest", line: "ignoring interface.defaultPrompt" }]
            }
          }
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
      "operational-maturity",
      "safe-wave",
      "execution-intelligence",
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
    expect(model.provider_log_summary?.total_lines).toBe(2);
    expect(model.provider_log_summary?.counts.plugin_manifest).toBe(1);
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

  test("builds execution intelligence detail from API response", () => {
    const model = buildRunDetailModel({
      run_id: "run_intel",
      status: "blocked",
      trust_status: "failed",
      apply_status: "blocked",
      total_events: 4,
      last_event_type: "runway.safe_wave_selected",
      safe_wave: ["task_a"],
      failures: [],
      timeline: [],
      execution_explanation: {
        schema: "waygent.execution_explanation.v1",
        run_id: "run_intel",
        status_summary: "run_intel has 1 scheduling barrier.",
        waves: [
          {
            wave_id: "wave_1",
            ready: ["task_a"],
            concurrency: 1,
            duration_ms: 1200,
            withheld: [{ task_id: "task_b", reason: "file_claim_conflict", detail: "README.md" }]
          }
        ],
        barriers: [
          {
            task_id: "task_b",
            reason: "file_claim_conflict",
            detail: "README.md",
            wave_id: "wave_1",
            category: "file_claim"
          }
        ],
        cost_hotspots: [
          {
            scope: "wave",
            phase: "wave",
            duration_ms: 1200,
            task_id: null,
            wave_id: "wave_1"
          }
        ],
        artifact_health: {
          indexed_count: 2,
          missing_count: 0,
          drift_count: 0,
          readiness_artifact_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"]
        },
        recommended_next_actions: ["Split overlapping file claims or add dependencies so safe waves can stay parallel."]
      }
    });

    expect(model.execution_explanation?.barriers[0]).toMatchObject({
      task_id: "task_b",
      category: "file_claim"
    });
    expect(model.sections.map((section) => section.id)).toContain("execution-intelligence");
  });

  test("builds operational maturity detail from shared API projections", () => {
    const model = buildRunDetailModel({
      run_id: "run_maturity",
      status: "completed",
      trust_status: "trusted",
      apply_status: "ready",
      total_events: 9,
      last_event_type: "lens.trust_report_updated",
      safe_wave: ["task_a"],
      failures: [],
      timeline: [],
      operational_maturity: {
        schema: "waygent.operational_maturity.v1",
        run_id: "run_maturity",
        hard_blocker: null,
        dogfood_evidence: {
          schema: "waygent.dogfood_evidence.v1",
          run_id: "run_maturity",
          status: "complete",
          dogfood_run_ref: null,
          checklist: [{ item: "artifact_index", status: "present", refs: ["artifacts/worker/task_a.json"], reason: null }],
          missing_reasons: [],
          real_runtime_timestamps: true,
          explain_summary: "no active failure barrier"
        },
        runtime_cost: {
          schema: "waygent.runtime_cost.v1",
          run_id: "run_maturity",
          estimated_wave_count: 1,
          measured_wave_count: 1,
          parallelism_score: 1,
          serial_barriers: [],
          phase_totals: [{ phase: "provider", duration_ms: 1200, task_ids: ["task_a"], wave_ids: [] }],
          top_hotspots: [{ scope: "task", phase: "provider", duration_ms: 1200, task_id: "task_a", wave_id: null }],
          fixed_costs: { provider: 1200 },
          recommended_next_actions: ["No trust-preserving optimization is recommended from the recorded evidence."]
        },
        provider_readiness: {
          schema: "waygent.provider_readiness.v1",
          run_id: "run_maturity",
          provider: "fake",
          status: "ready",
          command_summary: ["fake-provider"],
          stderr_summary: null,
          failure_class: null,
          attempt_refs: [],
          recommended_next_action: "Offline fake provider is ready for deterministic local checks."
        },
        apply_readiness: {
          status: "ready",
          reason: null,
          checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
          combined_patch_ref: "artifacts/checkpoints/apply/run_maturity.patch",
          source: "run_state_v2"
        },
        next_action: "No trust-preserving optimization is recommended from the recorded evidence.",
        projection_errors: []
      }
    });

    expect(model.sections.map((section) => section.id)).toContain("operational-maturity");
    expect(model.operational_maturity?.dogfood_evidence.status).toBe("complete");
    expect(model.dogfood_evidence?.checklist[0]).toMatchObject({ item: "artifact_index", status: "present" });
    expect(model.provider_readiness?.status).toBe("ready");
    expect(model.next_action).toBe("No trust-preserving optimization is recommended from the recorded evidence.");
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

  test("keeps console list apply disabled when API summary reports v2 blocker", () => {
    const run = realRunSummaryToConsoleRun({
      run_id: "run_needs_rebase",
      status: "blocked",
      trust_status: "trusted",
      apply_status: "blocked",
      total_events: 9,
      last_event_type: "runway.apply_dry_run_result"
    });

    expect(run.status).toBe("blocked");
    expect(run.applyStatus).toMatchObject({
      state: "blocked",
      canApply: false,
      reason: "blocked"
    });
  });

  test("does not infer apply readiness from successful verification events", () => {
    const run = realRunDetailToConsoleRun({
      run_id: "run_verified_but_blocked",
      status: "completed",
      trust_status: "trusted",
      apply_status: "ready",
      total_events: 2,
      last_event_type: "runway.verification_result",
      safe_wave: ["task_a"],
      failures: [],
      timeline: [
        { sequence: 1, phase: "platform", event_type: "platform.run_started", outcome: "running", summary: "Run opened." },
        { sequence: 2, phase: "runway", event_type: "runway.verification_result", outcome: "success", summary: "Verification passed." }
      ],
      verification: [
        {
          verification_id: "verify_task_a_1",
          task_id: "task_a",
          command: "bun test",
          status: "passed"
        }
      ],
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
    });

    expect(run.applyStatus).toMatchObject({
      state: "blocked",
      canApply: false,
      reason: "state_drift",
      checkpointRef: "artifacts/checkpoints/task_a/candidate_task_a.json"
    });
  });

  test("builds Workbench detail from operator decision projection", () => {
    const model = buildRunDetailModel({
      run_id: "run_workbench",
      status: "blocked",
      trust_status: "insufficient_evidence",
      apply_status: "blocked",
      total_events: 4,
      last_event_type: "runway.verification_result",
      safe_wave: [],
      failures: [],
      timeline: [
        { sequence: 1, phase: "platform", event_type: "platform.run_started", outcome: "running", summary: "Run opened." },
        { sequence: 2, phase: "runway", event_type: "runway.verification_result", outcome: "failed", summary: "Verification failed." }
      ],
      operator_decision: {
        schema: "waygent.operator_decision.v1",
        run_id: "run_workbench",
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
          summary: "run_workbench is blocked by verification_failed."
        },
        primary_blocker: {
          code: "verification_failed",
          title: "Verification failed",
          summary: "task_a failed verification.",
          severity: "blocking",
          task_id: "task_a",
          evidence_refs: ["verification:task_a"],
          missing_refs: [],
          recommended_action_ids: ["rerun_verification", "open_ai_repair_handoff"]
        },
        secondary_blockers: [],
        allowed_actions: [
          { id: "inspect_run", label: "Inspect run", reason: "safe", evidence_refs: ["state:state.json"], requires_approval: false, requires_runtime_revalidation: false, command: "waygent inspect --run run_workbench" },
          { id: "open_ai_repair_handoff", label: "Open AI repair handoff", reason: "safe", evidence_refs: ["state:state.json"], requires_approval: false, requires_runtime_revalidation: false, command: null }
        ],
        blocked_actions: [
          { id: "apply_run", label: "Apply run", reason: "Apply readiness is blocked by verification_failed.", evidence_refs: ["verification:task_a"], unblocks_when: "Verification passes." }
        ],
        evidence_packet: {
          state_refs: ["state:state.json"],
          event_refs: ["events:events.jsonl"],
          artifact_refs: [],
          verification_refs: ["verification:task_a"],
          checkpoint_refs: [],
          projection_refs: ["waygent.execution_explanation.v1"],
          missing_refs: [],
          redaction_notes: []
        },
        ai_handoff: {
          purpose: "draft_repair_plan",
          prompt_summary: "Draft a repair plan for verification_failed using bounded evidence.",
          run_id: "run_workbench",
          current_status: "blocked",
          primary_blocker: "verification_failed",
          secondary_blockers: [],
          allowed_action_ids: ["inspect_run", "open_ai_repair_handoff"],
          blocked_action_ids: ["apply_run"],
          constraints: ["Do not apply patches."],
          evidence_refs: ["verification:task_a"],
          missing_evidence: [],
          raw_fallback_refs: ["events:events.jsonl"],
          safety_notes: ["Waygent runtime remains apply authority."]
        },
        confidence: "deterministic",
        unknown_reasons: [],
        source_projection_refs: {
          run_state_v2: "state:state.json",
          apply_readiness: "waygent.apply_readiness",
          execution_explanation: "waygent.execution_explanation.v1",
          operational_maturity: "waygent.operational_maturity.v1"
        }
      }
    });

    expect(model.operator_decision?.primary_blocker?.code).toBe("verification_failed");
    expect(model.outcome_strip).toMatchObject({
      display_status: "blocked",
      primary_blocker: "verification_failed",
      next_action: "inspect_run",
      apply_status: "blocked",
      confidence: "deterministic"
    });
    expect(model.operator_timeline.map((row) => row.row_type)).toEqual(["raw_event", "verification_result"]);
    expect(model.sections.map((section) => section.id)).toContain("operator-decision");
    expect(model.sections.map((section) => section.id)).toContain("ai-handoff");
    expect(model.raw_evidence_refs).toEqual(["state:state.json", "events:events.jsonl"]);
  });

  test("surfaces intake recovery decision in Workbench detail", () => {
    const model = buildRunDetailModel({
      run_id: "run_intake",
      status: "blocked",
      trust_status: "insufficient_evidence",
      apply_status: "blocked",
      total_events: 2,
      last_event_type: "platform.intake_decision_required",
      safe_wave: [],
      failures: [],
      timeline: [
        { sequence: 1, phase: "platform", event_type: "platform.run_started", outcome: "running", summary: "Run opened." },
        { sequence: 2, phase: "intake", event_type: "platform.intake_decision_required", outcome: "blocked", summary: "Intake recovery requires a decision." }
      ],
      operator_decision: {
        schema: "waygent.operator_decision.v1",
        run_id: "run_intake",
        generated_at: "2026-05-23T00:00:00.000Z",
        status_summary: {
          display_status: "needs_input",
          runtime_status: "blocked",
          lifecycle_outcome: "blocked",
          current_phase: "preflight",
          active_tasks: 0,
          completed_tasks: 0,
          blocked_tasks: 0,
          apply_status: "blocked",
          summary: "run_intake is needs_input by intake_decision_required."
        },
        primary_blocker: {
          code: "intake_decision_required",
          title: "Intake recovery needs a decision",
          summary: "The plan contains a destructive command candidate. Confirm the intended safe replacement.",
          severity: "blocking",
          evidence_refs: ["state:state.json", "artifacts/intake/recovery-report.json"],
          missing_refs: ["destructive_command_candidate"],
          recommended_action_ids: ["request_user_input", "open_ai_repair_handoff", "open_raw_evidence"]
        },
        secondary_blockers: [],
        allowed_actions: [
          { id: "inspect_run", label: "Inspect run", reason: "safe", evidence_refs: ["state:state.json"], requires_approval: false, requires_runtime_revalidation: false, command: "waygent inspect --run run_intake" },
          { id: "request_user_input", label: "Request user input", reason: "needs decision", evidence_refs: ["state:state.json", "artifacts/intake/recovery-report.json"], requires_approval: true, requires_runtime_revalidation: true, command: null }
        ],
        blocked_actions: [
          { id: "apply_run", label: "Apply run", reason: "Apply readiness is blocked by intake_decision_required.", evidence_refs: ["state:state.json"], unblocks_when: "Intake recovery decision is resolved." }
        ],
        evidence_packet: {
          state_refs: ["state:state.json"],
          event_refs: ["events:events.jsonl"],
          artifact_refs: ["artifacts/intake/recovery-report.json"],
          verification_refs: [],
          checkpoint_refs: [],
          projection_refs: ["waygent.execution_explanation.v1"],
          missing_refs: [],
          redaction_notes: []
        },
        ai_handoff: {
          purpose: "draft_repair_plan",
          prompt_summary: "Draft a repair plan for intake_decision_required using bounded evidence.",
          run_id: "run_intake",
          current_status: "needs_input",
          primary_blocker: "intake_decision_required",
          secondary_blockers: [],
          allowed_action_ids: ["inspect_run", "request_user_input"],
          blocked_action_ids: ["apply_run"],
          constraints: ["Do not apply patches."],
          evidence_refs: ["artifacts/intake/recovery-report.json"],
          missing_evidence: [],
          raw_fallback_refs: ["events:events.jsonl"],
          safety_notes: ["Waygent runtime remains apply authority."]
        },
        confidence: "deterministic",
        unknown_reasons: [],
        intake_recovery: {
          status: "decision_required",
          can_start: false,
          confidence: "blocked",
          finding_codes: ["destructive_command_candidate"],
          artifact_refs: ["artifacts/intake/recovery-report.json"],
          question: "The plan contains a destructive command candidate. Confirm the intended safe replacement."
        },
        source_projection_refs: {
          run_state_v2: "state:state.json",
          apply_readiness: "waygent.apply_readiness",
          execution_explanation: "waygent.execution_explanation.v1",
          operational_maturity: "waygent.operational_maturity.v1"
        }
      }
    });

    expect(model.intake_recovery).toMatchObject({
      status: "decision_required",
      can_start: false,
      question: "The plan contains a destructive command candidate. Confirm the intended safe replacement."
    });
    expect(model.outcome_strip).toMatchObject({
      display_status: "needs_input",
      primary_blocker: "intake_decision_required",
      next_action: "inspect_run",
      intake_status: "decision_required",
      intake_question: "The plan contains a destructive command candidate. Confirm the intended safe replacement."
    });
    expect(model.sections.map((section) => section.id)).toContain("intake-recovery");
  });

  test("sorts run board by operator urgency", () => {
    const model = buildConsoleUiModel({
      generatedAt: "2026-05-22T00:00:00.000Z",
      runs: [
        { ...demoConsoleSnapshot.runs[0]!, runId: "run_done", title: "Done", status: "completed" },
        { ...demoConsoleSnapshot.runs[2]!, runId: "run_blocked", title: "Blocked", status: "blocked" },
        { ...demoConsoleSnapshot.runs[1]!, runId: "run_failed", title: "Failed", status: "failed" }
      ]
    });

    expect(model.runs.map((run) => run.runId)).toEqual(["run_blocked", "run_failed", "run_done"]);
  });
});
