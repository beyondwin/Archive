import { describe, expect, test } from "bun:test";
import {
  ContractValidationError,
  assertWaygentId,
  validateContract,
  type AgentLensEvent,
  type KernelExecutionRequest,
  type WaygentRunStateV2,
  type WorkerResult
} from "../src";

const event: AgentLensEvent = {
  schema: "agentlens.event.v3",
  event_id: "event_demo",
  agentlens_run_id: "run_lens",
  orchestrator_run_id: "run_orchestrator",
  producer: { name: "waygent", kind: "orchestrator", version: "0.1.0" },
  event_type: "runway.worker_result",
  occurred_at: "2026-05-21T00:00:00Z",
  sequence: 1,
  phase: "worker",
  outcome: "success",
  severity: "info",
  trust_impact: "supports_success",
  summary: "Worker produced bounded evidence.",
  payload: { task_id: "task_demo" }
};

const request: KernelExecutionRequest = {
  schema: "kernel.execution_request.v1",
  request_id: "exec_demo",
  run_id: "run_demo",
  task_id: "task_demo",
  kind: "process.exec",
  cwd: ".",
  argv: ["printf", "hello"],
  env: {},
  timeout_ms: 1000,
  stdin: "closed",
  tty: false,
  capture: { stdout_limit_bytes: 100, stderr_limit_bytes: 100 }
};

const workerResult: WorkerResult = {
  schema: "runway.worker_result.v1",
  task_id: "task_demo",
  candidate_id: "candidate_demo",
  status: "completed",
  changed_files: ["README.md"],
  summary: "Fake provider completed the task.",
  evidence: { provider: "fake-provider" }
};

function validOperatorDecisionFixture(overrides: Record<string, unknown> = {}) {
  return {
    schema: "waygent.operator_decision.v1",
    run_id: "run_review",
    generated_at: "2026-05-26T00:00:00.000Z",
    status_summary: {
      display_status: "blocked",
      runtime_status: "blocked",
      lifecycle_outcome: "blocked",
      current_phase: "complete",
      active_tasks: 0,
      completed_tasks: 1,
      blocked_tasks: 0,
      apply_status: "blocked",
      summary: "run_review requires review before apply."
    },
    primary_blocker: null,
    secondary_blockers: [],
    allowed_actions: [
      {
        id: "run_review",
        label: "Run review",
        reason: "Review evidence is required before apply.",
        evidence_refs: ["state:/tmp/run/state.json"],
        requires_approval: false,
        requires_runtime_revalidation: true,
        command: "waygent review --run run_review"
      }
    ],
    blocked_actions: [
      {
        id: "apply_run",
        label: "Apply run",
        reason: "Apply readiness is blocked until review passes.",
        evidence_refs: ["state:/tmp/run/state.json"],
        unblocks_when: "Spec and quality review pass."
      }
    ],
    evidence_packet: {
      state_refs: ["state:/tmp/run/state.json"],
      event_refs: ["events:/tmp/run/events.jsonl"],
      artifact_refs: [],
      verification_refs: ["verification:task_a"],
      checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
      projection_refs: ["waygent.operator_decision.v1"],
      recovered_failure_refs: ["event:event_run_3"],
      missing_refs: [],
      redaction_notes: []
    },
    ai_handoff: {
      purpose: "summarize_blocker",
      prompt_summary: "Summarize review and cost blockers.",
      run_id: "run_review",
      current_status: "blocked",
      primary_blocker: null,
      secondary_blockers: [],
      allowed_action_ids: ["run_review"],
      blocked_action_ids: ["apply_run"],
      constraints: ["Do not apply patches.", "Do not override Waygent runtime policy."],
      evidence_refs: ["state:/tmp/run/state.json"],
      missing_evidence: [],
      raw_fallback_refs: ["events:/tmp/run/events.jsonl"],
      safety_notes: ["Waygent runtime remains apply authority."]
    },
    confidence: "deterministic",
    unknown_reasons: [],
    source_projection_refs: {
      run_state_v2: "state:/tmp/run/state.json",
      apply_readiness: "waygent.apply_readiness",
      execution_explanation: "waygent.execution_explanation.v1",
      operational_maturity: "waygent.operational_maturity.v1"
    },
    ...overrides
  };
}

describe("Waygent contracts", () => {
  test("normalizes shared id primitives", () => {
    expect(assertWaygentId("run_demo")).toBe("run_demo");
    expect(() => assertWaygentId("Bad Id")).toThrow();
  });

  test("accepts canonical AgentLens events", () => {
    expect(validateContract("agentlens.event.v3", event)).toEqual(event);
  });

  test("rejects legacy event namespaces", () => {
    expect(() =>
      validateContract("agentlens.event.v3", { ...event, event_type: "kws-cpe.worker_result" })
    ).toThrow(ContractValidationError);
  });

  test("accepts kernel execution request and result contracts", () => {
    expect(validateContract("kernel.execution_request.v1", request)).toEqual(request);
    expect(
      validateContract("kernel.execution_result.v1", {
        schema: "kernel.execution_result.v1",
        request_id: "exec_demo",
        run_id: "run_demo",
        task_id: "task_demo",
        exit_code: 0,
        signal: null,
        timed_out: false,
        stdout: "hello",
        stderr: "",
        stdout_truncated: false,
        stderr_truncated: false,
        stdout_sha256: "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        stderr_sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        changed_files: []
      })
    ).toBeTruthy();
  });

  test("worker_result.v1 accepts optional patch_ref / patch_sha256 / patch_byte_length in evidence", () => {
    const workerResult = {
      schema: "runway.worker_result.v1",
      task_id: "task_a",
      candidate_id: "cand_a",
      status: "completed",
      changed_files: ["src/foo.ts"],
      summary: "done",
      evidence: {
        patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
        patch_sha256: "a".repeat(64),
        patch_byte_length: 12345
      }
    };
    expect(validateContract("runway.worker_result.v1", workerResult)).toEqual(workerResult);
  });

  test("accepts worker results and provider manifests", () => {
    expect(validateContract("runway.worker_result.v1", workerResult)).toEqual(workerResult);
    expect(
      validateContract("provider.capability_manifest.v1", {
        schema: "provider.capability_manifest.v1",
        provider: "fake",
        supported_modes: ["single-agent", "multi-agent"],
        tool_calls: true,
        file_edits: true,
        shell: false,
        streaming: false,
        approvals: false,
        result_schema: "runway.worker_result.v1"
      })
    ).toBeTruthy();
  });

  test("validates task review artifacts", () => {
    const artifact = {
      schema: "waygent.task_review.v1",
      run_id: "run_review",
      task_id: "task_a",
      review_id: "review_task_a_spec_1",
      role: "spec_reviewer",
      status: "passed",
      verdict: "approved",
      issues: [],
      evidence_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
      reviewed_patch_refs: ["artifacts/checkpoints/task_a/candidate_task_a.patch"],
      model: "fake-reviewer",
      created_at: "2026-05-26T00:00:00.000Z"
    };

    expect(validateContract("waygent.task_review.v1", artifact)).toEqual(artifact);
  });

  test("validates operator decision review and cost additions", () => {
    const decision = validOperatorDecisionFixture({
      review_status: {
        required: true,
        missing_task_ids: ["task_a"],
        passed_task_ids: []
      },
      recovered_failures: [
        {
          task_id: "task_a",
          failure_class: "malformed_result",
          evidence_refs: ["event:event_run_3"]
        }
      ],
      cost_summary: {
        cost_usd: 57.25,
        dispatches: 4,
        budget_status: "warning"
      },
      stale_run_status: {
        run_id: "run_review",
        stale: true,
        reason: "heartbeat_expired",
        safe_actions: ["inspect", "mark_blocked", "resume"]
      }
    });

    expect(validateContract("waygent.operator_decision.v1", decision)).toEqual(decision);
  });

  test("validates operator recoverable evidence projection additions", () => {
    const decision = validOperatorDecisionFixture({
      recoverable_evidence: [
        {
          task_id: "task_a",
          failure_class: "malformed_result",
          kind: "recoverable_patch",
          patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
          salvage_ref: "artifacts/salvage/task_a/attempt_task_a_1.json",
          recommended_action: "salvage_then_review",
          evidence_refs: [
            "artifacts/provider/attempt_task_a_1.stdout.txt",
            "artifacts/worker/task_a/attempt_1_patch.diff"
          ]
        }
      ],
      why_not_apply_ready: {
        reason: "review_evidence_missing",
        missing_contracts: ["review_evidence"],
        evidence_refs: ["state:/tmp/run/state.json"]
      }
    });

    expect(validateContract("waygent.operator_decision.v1", decision)).toEqual(decision);
  });

  test("rejects malformed recoverable evidence projection additions", () => {
    const decision = validOperatorDecisionFixture({
      recoverable_evidence: [
        {
          task_id: "task_a",
          failure_class: "verification_failed",
          kind: "recoverable_patch",
          patch_ref: "",
          salvage_ref: null,
          recommended_action: "unknown_action",
          evidence_refs: []
        }
      ],
      why_not_apply_ready: {
        reason: "",
        missing_contracts: [],
        evidence_refs: []
      }
    });

    expect(() => validateContract("waygent.operator_decision.v1", decision)).toThrow(ContractValidationError);
  });

  test("validates salvage results", () => {
    const salvageResult = {
      schema: "waygent.salvage_result.v1",
      task_id: "task_a",
      attempt_id: "attempt_task_a_1",
      status: "salvaged_patch",
      patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
      changed_files: ["packages/orchestrator/src/example.ts"],
      reason: null,
      evidence_refs: ["artifacts/provider/attempt_task_a_1.stderr.txt"]
    };

    expect(validateContract("waygent.salvage_result.v1", salvageResult)).toEqual(salvageResult);
  });

  test("task packet context budget can include shrink actions", () => {
    const packet = validateContract("waygent.task_packet.v1", {
      schema: "waygent.task_packet.v1",
      run_id: "run_context",
      task_id: "task_context",
      role: "implement",
      task_title: "Context task",
      plan_excerpt: "Do the work",
      spec_excerpt: "Spec section",
      file_claims: [],
      allowed_write_globs: [],
      forbidden_write_globs: [".git/**"],
      dependencies: [],
      checkpoint_inputs: [],
      acceptance_commands: ["printf hello"],
      verification_commands: ["printf hello"],
      risk: "low",
      previous_failures: [
        {
          failure_class: "context_missing",
          evidence_refs: ["artifacts/task_packets/task_context.json"],
          summary: "Task packet exceeded the provider context budget."
        }
      ],
      decisions: [],
      context_budget: {
        estimated_chars: 120000,
        max_chars: 60000,
        status: "red",
        shrink_actions: ["replace_full_logs_with_digest"]
      },
      sha256: "a".repeat(64)
    }) as { context_budget: { status: string; shrink_actions?: string[] } };

    expect(packet.context_budget.status).toBe("red");
    expect(packet.context_budget.shrink_actions).toEqual(["replace_full_logs_with_digest"]);
  });

  test("validates lens runway projection contract", () => {
    expect(
      validateContract("lens.runway_projection.v1", {
        schema: "lens.runway_projection.v1",
        run_id: "run_demo",
        status: "completed",
        safe_wave: ["task_demo"],
        trust_status: "trusted",
        event_count: 6
      })
    ).toMatchObject({
      schema: "lens.runway_projection.v1",
      run_id: "run_demo"
    });

    expect(() =>
      validateContract("lens.runway_projection.v1", {
        schema: "lens.runway_projection.v1",
        run_id: "run_projection_extra",
        status: "completed",
        safe_wave: [],
        trust_status: "trusted",
        event_count: 1,
        [["legacy", "source"].join("_")]: "old-runtime"
      })
    ).toThrow(ContractValidationError);
  });

  test("accepts additive Waygent v2 state preflight, worktree, and provider process evidence", () => {
    const state: WaygentRunStateV2 = {
      schema: "waygent.run_state.v2",
      run_id: "run_demo",
      workspace: "/tmp/workspace",
      source_branch: "main",
      worktree_root: "/tmp/worktrees",
      run_root: "/tmp/run",
      artifact_root: "/tmp/run/artifacts",
      state_path: "/tmp/run/state.json",
      event_journal_path: "/tmp/run/events.jsonl",
      plan_path: null,
      spec_path: null,
      provider_profile: { provider: "fake" },
      status: "completed",
      lifecycle_outcome: "finished",
      current_phase: "complete",
      preflight: {
        status: "dirty_unrelated",
        dirty_files: ["notes/scratch.md"],
        related: [],
        unrelated: ["notes/scratch.md"],
        checked_at: "2026-05-21T00:00:00Z",
        reason: "dirty_unrelated_source_checkout",
        decision_packet_ref: null
      },
      worktrees: [
        {
          task_id: "task_demo",
          branch: "waygent/run_demo/task_demo",
          path: "/tmp/worktrees/task_demo",
          source: "/tmp/workspace",
          source_commit: "abc123",
          cleanup_status: "failed"
        }
      ],
      artifact_index: [
        {
          ref: "artifacts/worker/task_demo.json",
          media_type: "application/json",
          sha256: "a".repeat(64),
          byte_length: 42,
          producer_phase: "provider",
          task_id: "task_demo",
          created_at: "2026-05-22T00:00:00.000Z"
        }
      ],
      tasks: {
        task_demo: {
          id: "task_demo",
          status: "verified",
          risk: "low",
          dependencies: [],
          file_claims: [{ path: "README.md", mode: "owned" }],
          attempts: ["attempt_demo"],
          task_packet_path: null,
          task_packet_sha256: null,
          unit_manifest: null,
          checkpoint_refs: ["artifacts/checkpoints/task_demo/candidate_task_demo.json"],
          latest_failure_class: null,
          decision_packet_ref: null,
          timing: {},
          phase_timings: [
            {
              phase: "provider",
              started: "2026-05-22T00:00:00.000Z",
              completed: "2026-05-22T00:00:01.000Z",
              duration_ms: 1000
            }
          ]
        }
      },
      safe_waves: [{
        wave_id: "wave_1",
        ready: ["task_demo"],
        withheld: [],
        concurrency: 1,
        timing: {
          started: "2026-05-21T00:00:00Z",
          completed: "2026-05-21T00:00:01Z",
          duration_ms: 1000
        }
      }],
      provider_attempts: [
        {
          schema: "runway.provider_attempt.v1",
          attempt_id: "attempt_demo",
          run_id: "run_demo",
          task_id: "task_demo",
          role: "implement",
          provider: "fake",
          command: ["fake-provider"],
          cwd: "/tmp/worktrees/task_demo",
          stdin_ref: "artifacts/provider/stdin.json",
          stdout_ref: "artifacts/provider/stdout.txt",
          stderr_ref: "artifacts/provider/stderr.txt",
          event_stream_ref: null,
          exit_code: 0,
          timed_out: false,
          started_at: "2026-05-21T00:00:00Z",
          completed_at: "2026-05-21T00:00:01Z",
          worker_result_ref: "artifacts/provider/worker-result.json",
          failure_class: null,
          process: {
            stdout: "completed\n",
            stderr: "",
            exit_code: 0,
            timed_out: false,
            started_at: "2026-05-21T00:00:00Z",
            completed_at: "2026-05-21T00:00:01Z",
            event_stream: null,
            stderr_summary: {
              total_lines: 5,
              counts: {
                error: 1,
                warning: 1,
                mcp: 1,
                plugin_manifest: 1,
                skill_loader: 1,
                other: 0
              },
              samples: [
                { category: "error", line: "ERROR failed to load skill" },
                { category: "plugin_manifest", line: "ignoring interface.defaultPrompt" }
              ]
            }
          }
        }
      ],
      reviews: [],
      verification: [],
      recovery: [],
      apply: { status: "not_applied" },
      context: { snapshot_path: null, basis_hash: null },
      drift: { last_checked_at: "2026-05-21T00:00:02Z", records: [], unrepaired_blockers: [] },
      completion_audit: {
        status: "passed",
        combined_apply_evidence: {
          status: "passed",
          checkpoint_refs: ["artifacts/checkpoints/task_demo/candidate_task_demo.json"],
          patch_ref: "artifacts/checkpoints/apply/run_demo.patch"
        }
      },
      repair_budget: {
        task_demo: {
          max_attempts: 2,
          current: 1
        }
      },
      timestamps: {
        started_at: "2026-05-21T00:00:00Z",
        updated_at: "2026-05-21T00:00:02Z",
        completed_at: "2026-05-21T00:00:02Z"
      }
    };

    expect(validateContract("waygent.run_state.v2", state)).toEqual(state);
  });

  test("accepts intake recovery state and operator projection summary", () => {
    const intake = {
      status: "recovered",
      started_at: "2026-05-23T00:00:00.000Z",
      completed_at: "2026-05-23T00:00:01.000Z",
      normalized_plan_ref: "artifacts/intake/normalized-plan.md",
      recovery_report_ref: "artifacts/intake/recovery-report.json",
      findings: [
        {
          code: "task_body_not_yaml",
          severity: "warning",
          message: "Task 1 used prose instead of waygent-task YAML.",
          task_id: "task_1_update_readme",
          evidence_refs: ["plan:plan.md#task-1"]
        }
      ],
      repair_actions: [
        {
          action: "deterministic_superpowers_normalization",
          status: "applied",
          reason: "Recovered file claims and verification commands from markdown sections.",
          evidence_refs: ["artifacts/intake/normalized-plan.md"]
        }
      ],
      can_start: true,
      confidence: "deterministic",
      question: null
    };

    const state: WaygentRunStateV2 = {
      schema: "waygent.run_state.v2",
      run_id: "run_intake",
      workspace: "/tmp/workspace",
      source_branch: "main",
      worktree_root: "/tmp/worktrees",
      run_root: "/tmp/run",
      artifact_root: "/tmp/run/artifacts",
      state_path: "/tmp/run/state.json",
      event_journal_path: "/tmp/run/events.jsonl",
      plan_path: "/tmp/workspace/plan.md",
      spec_path: "/tmp/workspace/spec.md",
      provider_profile: { provider: "fake" },
      intake_recovery: intake,
      status: "completed",
      lifecycle_outcome: "finished",
      current_phase: "complete",
      tasks: {},
      safe_waves: [],
      provider_attempts: [],
      reviews: [],
      verification: [],
      recovery: [],
      apply: { status: "not_applied" },
      context: { snapshot_path: null, basis_hash: null },
      drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
      completion_audit: null,
      timestamps: {
        started_at: "2026-05-23T00:00:00.000Z",
        updated_at: "2026-05-23T00:00:01.000Z",
        completed_at: "2026-05-23T00:00:01.000Z"
      }
    };

    expect(validateContract("waygent.run_state.v2", state)).toEqual(state);

    const decision = validateContract("waygent.operator_decision.v1", {
      schema: "waygent.operator_decision.v1",
      run_id: "run_intake",
      generated_at: "2026-05-23T00:00:02.000Z",
      status_summary: {
        display_status: "done",
        runtime_status: "completed",
        lifecycle_outcome: "finished",
        current_phase: "complete",
        active_tasks: 0,
        completed_tasks: 0,
        blocked_tasks: 0,
        apply_status: "not_ready",
        summary: "run_intake completed after deterministic intake recovery."
      },
      primary_blocker: null,
      secondary_blockers: [],
      allowed_actions: [],
      blocked_actions: [],
      evidence_packet: {
        state_refs: ["state:/tmp/run/state.json"],
        event_refs: [],
        artifact_refs: ["artifacts/intake/normalized-plan.md", "artifacts/intake/recovery-report.json"],
        verification_refs: [],
        checkpoint_refs: [],
        projection_refs: [],
        missing_refs: [],
        redaction_notes: []
      },
      ai_handoff: {
        purpose: "summarize_blocker",
        prompt_summary: "Summarize the intake recovery result.",
        run_id: "run_intake",
        current_status: "done",
        primary_blocker: null,
        secondary_blockers: [],
        allowed_action_ids: [],
        blocked_action_ids: [],
        constraints: ["Do not override Waygent runtime policy."],
        evidence_refs: ["artifacts/intake/recovery-report.json"],
        missing_evidence: [],
        raw_fallback_refs: [],
        safety_notes: ["Waygent runtime remains apply authority."]
      },
      confidence: "deterministic",
      unknown_reasons: [],
      intake_recovery: {
        status: "recovered",
        can_start: true,
        confidence: "deterministic",
        finding_codes: ["task_body_not_yaml"],
        artifact_refs: ["artifacts/intake/normalized-plan.md", "artifacts/intake/recovery-report.json"],
        question: null
      },
      source_projection_refs: {
        run_state_v2: "state:/tmp/run/state.json",
        apply_readiness: "waygent.apply_readiness",
        execution_explanation: "waygent.execution_explanation.v1",
        operational_maturity: "waygent.operational_maturity.v1"
      }
    }) as { intake_recovery?: { status: string; can_start: boolean } };

    expect(decision.intake_recovery).toMatchObject({ status: "recovered", can_start: true });
  });

  test("validates operator decision projection contract", () => {
    const decision = {
      schema: "waygent.operator_decision.v1",
      run_id: "run_demo",
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
        summary: "run_demo is blocked by verification_failed."
      },
      primary_blocker: {
        code: "verification_failed",
        title: "Verification failed",
        summary: "task_demo failed verification.",
        severity: "blocking",
        task_id: "task_demo",
        evidence_refs: ["state:/tmp/run/state.json", "verification:task_demo"],
        missing_refs: [],
        recommended_action_ids: ["rerun_verification", "open_ai_repair_handoff"]
      },
      secondary_blockers: [],
      allowed_actions: [
        {
          id: "inspect_run",
          label: "Inspect run",
          reason: "Inspection is always safe.",
          evidence_refs: ["state:/tmp/run/state.json"],
          requires_approval: false,
          requires_runtime_revalidation: false,
          command: "waygent inspect --run run_demo"
        },
        {
          id: "open_ai_repair_handoff",
          label: "Open AI repair handoff",
          reason: "AI can draft a repair plan from bounded evidence.",
          evidence_refs: ["state:/tmp/run/state.json"],
          requires_approval: false,
          requires_runtime_revalidation: false,
          command: null
        }
      ],
      blocked_actions: [
        {
          id: "apply_run",
          label: "Apply run",
          reason: "Apply readiness is blocked by verification_failed.",
          evidence_refs: ["state:/tmp/run/state.json"],
          unblocks_when: "Verification and apply readiness pass."
        }
      ],
      evidence_packet: {
        state_refs: ["state:/tmp/run/state.json"],
        event_refs: ["events:/tmp/run/events.jsonl"],
        artifact_refs: [],
        verification_refs: ["verification:task_demo"],
        checkpoint_refs: [],
        projection_refs: ["waygent.execution_explanation.v1"],
        missing_refs: [],
        redaction_notes: []
      },
      ai_handoff: {
        purpose: "draft_repair_plan",
        prompt_summary: "Draft a repair plan for verification_failed using bounded evidence.",
        run_id: "run_demo",
        current_status: "blocked",
        primary_blocker: "verification_failed",
        secondary_blockers: [],
        allowed_action_ids: ["inspect_run", "open_ai_repair_handoff"],
        blocked_action_ids: ["apply_run"],
        constraints: [
          "Do not apply patches.",
          "Do not mutate source.",
          "Do not override Waygent runtime policy."
        ],
        evidence_refs: ["state:/tmp/run/state.json", "verification:task_demo"],
        missing_evidence: [],
        raw_fallback_refs: ["events:/tmp/run/events.jsonl"],
        safety_notes: ["Waygent runtime remains apply authority."]
      },
      confidence: "deterministic",
      unknown_reasons: [],
      source_projection_refs: {
        run_state_v2: "state:/tmp/run/state.json",
        apply_readiness: "waygent.apply_readiness",
        execution_explanation: "waygent.execution_explanation.v1",
        operational_maturity: "waygent.operational_maturity.v1"
      }
    };

    expect(validateContract("waygent.operator_decision.v1", decision)).toEqual(decision);
    expect(() =>
      validateContract("waygent.operator_decision.v1", {
        ...decision,
        [["legacy", "source"].join("_")]: "components/agentlens"
      })
    ).toThrow(ContractValidationError);
  });

  test("WaygentRunStateV2 type accepts optional repair_budget keyed by task_id", () => {
    const state: import("../src/types").WaygentRunStateV2 = {
      schema: "waygent.run_state.v2",
      run_id: "run_repair_state",
      workspace: "/tmp/ws",
      source_branch: null,
      worktree_root: "/tmp/wt",
      run_root: "/tmp/run",
      artifact_root: "/tmp/run/artifacts",
      state_path: "/tmp/run/state.json",
      event_journal_path: "/tmp/run/events.jsonl",
      plan_path: null,
      spec_path: null,
      provider_profile: { provider: "fake" },
      status: "completed",
      lifecycle_outcome: "finished",
      current_phase: "complete",
      tasks: {},
      safe_waves: [],
      provider_attempts: [],
      reviews: [],
      verification: [],
      recovery: [],
      apply: { status: "not_applied" },
      context: { snapshot_path: null, basis_hash: null },
      drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
      completion_audit: null,
      timestamps: { started_at: "2026-05-25T00:00:00Z", updated_at: "2026-05-25T00:00:00Z", completed_at: null },
      repair_budget: { task_a: { max_attempts: 2, current: 0 } }
    };
    expect(state.repair_budget?.task_a?.max_attempts).toBe(2);
  });
});
