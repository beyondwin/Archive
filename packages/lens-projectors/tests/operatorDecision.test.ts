import { describe, expect, test } from "bun:test";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import { projectOperatorDecisionFromState } from "../src";
import { demoEvent } from "./support";

describe("operator decision projector", () => {
  test("allows apply only when apply readiness is ready", () => {
    const state = makeState({
      completion_audit: {
        status: "passed",
        combined_apply_evidence: {
          status: "passed",
          checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
          patch_ref: "artifacts/checkpoints/apply/run_ready.patch"
        }
      }
    });

    const projection = projectOperatorDecisionFromState({
      state,
      events: [demoEvent({ event_type: "runway.verification_result", outcome: "success" })]
    });

    expect(projection).toMatchObject({
      schema: "waygent.operator_decision.v1",
      run_id: "run_demo",
      confidence: "deterministic",
      primary_blocker: null,
      status_summary: {
        display_status: "ready_to_apply",
        apply_status: "ready"
      }
    });
    expect(projection.allowed_actions.map((action) => action.id)).toContain("apply_run");
    expect(projection.blocked_actions.map((action) => action.id)).not.toContain("apply_run");
  });

  test("blocks apply and exposes repair handoff for verification failure", () => {
    const projection = projectOperatorDecisionFromState({
      state: makeState({
        status: "blocked",
        lifecycle_outcome: "blocked",
        current_phase: "recover",
        tasks: {
          task_a: task("task_a", {
            status: "blocked",
            latest_failure_class: "verification_failed",
            checkpoint_refs: []
          })
        },
        verification: [{ verification_id: "verify_task_a_1", task_id: "task_a", command: "bun test", status: "failed" }],
        apply: { status: "blocked", reason: "verification_failed" }
      }),
      events: [demoEvent({ event_type: "runway.verification_result", outcome: "failed", summary: "Verification failed." })]
    });

    expect(projection.primary_blocker).toMatchObject({
      code: "verification_failed",
      task_id: "task_a",
      severity: "blocking"
    });
    expect(projection.allowed_actions.map((action) => action.id)).toEqual([
      "inspect_run",
      "explain_run",
      "open_raw_evidence",
      "open_ai_repair_handoff",
      "rerun_verification"
    ]);
    expect(projection.blocked_actions).toContainEqual(expect.objectContaining({
      id: "apply_run",
      reason: expect.stringContaining("verification_failed")
    }));
    expect(projection.ai_handoff.constraints).toContain("Do not apply patches.");
    expect(projection.ai_handoff.evidence_refs).toContain("verification:task_a");
  });

  test("classifies checkpoint dry-run conflict as needs_rebase", () => {
    const projection = projectOperatorDecisionFromState({
      state: makeState({
        status: "blocked",
        lifecycle_outcome: "blocked",
        current_phase: "recover",
        tasks: {
          task_a: task("task_a", {
            status: "blocked",
            latest_failure_class: "needs_rebase",
            checkpoint_refs: []
          })
        },
        drift: {
          last_checked_at: "2026-05-22T00:01:00.000Z",
          records: [{ failure_class: "needs_rebase", files: ["README.md"] }],
          unrepaired_blockers: [{ failure_class: "needs_rebase", files: ["README.md"] }]
        },
        apply: { status: "blocked", reason: "needs_rebase" }
      }),
      events: []
    });

    expect(projection.primary_blocker).toMatchObject({
      code: "needs_rebase",
      recommended_action_ids: ["regenerate_checkpoint", "rebase_checkpoint", "open_ai_repair_handoff"]
    });
    expect(projection.allowed_actions.map((action) => action.id)).toContain("regenerate_checkpoint");
    expect(projection.allowed_actions.map((action) => action.id)).toContain("rebase_checkpoint");
  });

  test("degrades missing state to unknown confidence with raw evidence only", () => {
    const projection = projectOperatorDecisionFromState({
      state: null,
      state_error: { status: "missing", reason: "missing_run_state_v2" },
      events: [demoEvent({ event_type: "runway.worker_result", outcome: "success" })],
      run_id: "run_missing"
    });

    expect(projection).toMatchObject({
      run_id: "run_missing",
      confidence: "unknown",
      primary_blocker: {
        code: "state_missing",
        severity: "critical"
      }
    });
    expect(projection.allowed_actions.map((action) => action.id)).toEqual([
      "inspect_run",
      "open_raw_evidence"
    ]);
    expect(projection.blocked_actions.map((action) => action.id)).toContain("apply_run");
  });

  test("surfaces intake decision blocker and recovery summary", () => {
    const projection = projectOperatorDecisionFromState({
      state: makeState({
        status: "blocked",
        lifecycle_outcome: "blocked",
        current_phase: "preflight",
        tasks: {},
        safe_waves: [],
        artifact_index: [],
        apply: { status: "blocked", reason: "intake_decision_required" },
        intake_recovery: {
          status: "decision_required",
          started_at: "2026-05-22T00:00:00.000Z",
          completed_at: "2026-05-22T00:00:01.000Z",
          normalized_plan_ref: null,
          recovery_report_ref: "artifacts/intake/recovery-report.json",
          findings: [{
            code: "destructive_command_candidate",
            severity: "blocking",
            message: "Plan contains a destructive command candidate.",
            task_id: null,
            evidence_refs: ["plan:plan.md"]
          }],
          repair_actions: [{
            action: "deterministic_markdown_intake_repair",
            status: "blocked",
            reason: "High-risk ambiguity prevents automatic execution.",
            evidence_refs: ["plan:plan.md"]
          }],
          can_start: false,
          confidence: "blocked",
          question: "The plan contains a destructive command candidate. Confirm the intended safe replacement."
        }
      }),
      events: []
    });

    expect(projection.primary_blocker).toMatchObject({
      code: "intake_decision_required",
      severity: "blocking",
      summary: "The plan contains a destructive command candidate. Confirm the intended safe replacement."
    });
    expect(projection.status_summary).toMatchObject({
      display_status: "needs_input",
      apply_status: "blocked"
    });
    expect(projection.allowed_actions.map((action) => action.id)).toContain("request_user_input");
    expect(projection.allowed_actions.map((action) => action.id)).toContain("open_ai_repair_handoff");
    expect(projection.blocked_actions.map((action) => action.id)).toContain("apply_run");
    expect(projection.intake_recovery).toEqual({
      status: "decision_required",
      can_start: false,
      confidence: "blocked",
      finding_codes: ["destructive_command_candidate"],
      artifact_refs: ["artifacts/intake/recovery-report.json"],
      question: "The plan contains a destructive command candidate. Confirm the intended safe replacement."
    });
    expect(projection.evidence_packet.artifact_refs).toContain("artifacts/intake/recovery-report.json");
  });

  test("classifies intake recovery failure as blocking", () => {
    const projection = projectOperatorDecisionFromState({
      state: makeState({
        status: "blocked",
        lifecycle_outcome: "blocked",
        current_phase: "preflight",
        tasks: {},
        safe_waves: [],
        artifact_index: [],
        apply: { status: "blocked", reason: "intake_decision_required" },
        intake_recovery: {
          status: "failed",
          started_at: "2026-05-22T00:00:00.000Z",
          completed_at: "2026-05-22T00:00:01.000Z",
          normalized_plan_ref: null,
          recovery_report_ref: "artifacts/intake/recovery-report.json",
          findings: [{
            code: "task_body_not_yaml",
            severity: "blocking",
            message: "Plan body was not recoverable.",
            task_id: null,
            evidence_refs: ["plan:plan.md"]
          }],
          repair_actions: [],
          can_start: false,
          confidence: "blocked",
          question: null
        }
      }),
      events: []
    });

    expect(projection.primary_blocker).toMatchObject({
      code: "intake_recovery_failed",
      severity: "blocking"
    });
    expect(projection.status_summary.display_status).toBe("blocked");
    expect(projection.intake_recovery?.status).toBe("failed");
    expect(projection.intake_recovery?.can_start).toBe(false);
  });

  test("includes intake recovery summary for recovered runs without a blocker", () => {
    const projection = projectOperatorDecisionFromState({
      state: makeState({
        intake_recovery: {
          status: "recovered",
          started_at: "2026-05-22T00:00:00.000Z",
          completed_at: "2026-05-22T00:00:01.000Z",
          normalized_plan_ref: "artifacts/intake/normalized-plan.md",
          recovery_report_ref: "artifacts/intake/recovery-report.json",
          findings: [{
            code: "task_body_not_yaml",
            severity: "warning",
            message: "Plan body was recovered from markdown headings.",
            task_id: null,
            evidence_refs: ["plan:plan.md"]
          }],
          repair_actions: [{
            action: "deterministic_markdown_intake_repair",
            status: "applied",
            reason: "Recovered tasks from markdown sections.",
            evidence_refs: ["artifacts/intake/normalized-plan.md"]
          }],
          can_start: true,
          confidence: "deterministic",
          question: null
        },
        completion_audit: {
          status: "passed",
          combined_apply_evidence: {
            status: "passed",
            checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
            patch_ref: "artifacts/checkpoints/apply/run_ready.patch"
          }
        }
      }),
      events: []
    });

    expect(projection.primary_blocker).toBeNull();
    expect(projection.intake_recovery).toEqual({
      status: "recovered",
      can_start: true,
      confidence: "deterministic",
      finding_codes: ["task_body_not_yaml"],
      artifact_refs: ["artifacts/intake/normalized-plan.md", "artifacts/intake/recovery-report.json"],
      question: null
    });
    expect(projection.evidence_packet.artifact_refs).toEqual(
      expect.arrayContaining([
        "artifacts/intake/normalized-plan.md",
        "artifacts/intake/recovery-report.json"
      ])
    );
  });

  test("marks missing evidence as partial confidence", () => {
    const projection = projectOperatorDecisionFromState({
      state: makeState({
        artifact_index: [],
        tasks: {
          task_a: task("task_a", {
            status: "verified",
            checkpoint_refs: []
          })
        },
        apply: { status: "not_ready" },
        completion_audit: { status: "passed" }
      }),
      events: []
    });

    expect(projection.confidence).toBe("partial");
    expect(projection.evidence_packet.missing_refs).toContain("checkpoint_refs");
    expect(projection.primary_blocker).toMatchObject({
      code: "checkpoint_missing"
    });
  });
});

function task(
  id: string,
  overrides: Partial<WaygentRunStateV2["tasks"][string]> = {}
): WaygentRunStateV2["tasks"][string] {
  return {
    id,
    status: "verified",
    risk: "low",
    dependencies: [],
    file_claims: [{ path: `${id}.txt`, mode: "owned" }],
    attempts: [],
    task_packet_path: null,
    task_packet_sha256: null,
    unit_manifest: null,
    checkpoint_refs: [`artifacts/checkpoints/${id}/candidate_${id}.json`],
    latest_failure_class: null,
    decision_packet_ref: null,
    timing: {},
    ...overrides
  };
}

function makeState(overrides: Partial<WaygentRunStateV2> = {}): WaygentRunStateV2 {
  return {
    schema: "waygent.run_state.v2",
    run_id: "run_demo",
    workspace: "/tmp/source",
    source_branch: "main",
    worktree_root: "/tmp/worktrees",
    run_root: "/tmp/run_demo",
    artifact_root: "/tmp/run_demo/artifacts",
    state_path: "/tmp/run_demo/state.json",
    event_journal_path: "/tmp/run_demo/events.jsonl",
    plan_path: null,
    spec_path: null,
    provider_profile: { provider: "fake" },
    status: "completed",
    lifecycle_outcome: "finished",
    current_phase: "complete",
    tasks: {
      task_a: task("task_a")
    },
    safe_waves: [],
    provider_attempts: [],
    reviews: [],
    verification: [],
    recovery: [],
    artifact_index: [
      artifact("artifacts/checkpoints/task_a/candidate_task_a.json", "checkpoint", "task_a"),
      artifact("artifacts/checkpoints/apply/run_ready.patch", "combined_apply", null)
    ],
    apply: { status: "not_ready" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: null,
    timestamps: {
      started_at: "2026-05-22T00:00:00.000Z",
      updated_at: "2026-05-22T00:00:01.000Z",
      completed_at: "2026-05-22T00:00:01.000Z"
    },
    ...overrides
  };
}

function artifact(
  ref: string,
  producerPhase: NonNullable<WaygentRunStateV2["artifact_index"]>[number]["producer_phase"],
  taskId: string | null
): NonNullable<WaygentRunStateV2["artifact_index"]>[number] {
  return {
    ref,
    media_type: "application/json",
    sha256: "a".repeat(64),
    byte_length: 12,
    producer_phase: producerPhase,
    task_id: taskId,
    created_at: "2026-05-22T00:00:01.000Z"
  };
}
