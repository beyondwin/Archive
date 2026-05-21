import { describe, expect, test } from "bun:test";
import type { AgentLensEvent, WaygentRunStateV2 } from "@waygent/contracts";
import {
  projectDogfoodEvidenceFromState,
  projectOperationalMaturityFromState,
  projectProviderReadinessFromState,
  projectRuntimeCostFromState
} from "../src";
import { demoEvent } from "./support";

describe("operational maturity projectors", () => {
  test("marks dogfood evidence complete when durable execution evidence is present", () => {
    const state = makeState();
    const projection = projectDogfoodEvidenceFromState({ state, events: eventsFor(state.run_id) });

    expect(projection).toMatchObject({
      schema: "waygent.dogfood_evidence.v1",
      run_id: state.run_id,
      status: "complete"
    });
    const artifactIndexItem = projection.checklist.find((item) => item.item === "artifact_index");
    expect(artifactIndexItem).toMatchObject({ status: "present" });
    expect(artifactIndexItem?.refs).toContain("artifacts/worker/task_a.json");
    expect(artifactIndexItem?.refs).toContain("artifacts/checkpoints/task_a/candidate_task_a.json");
    expect(projection.checklist.find((item) => item.item === "task_phase_timings")).toMatchObject({
      status: "present"
    });
  });

  test("keeps missing dogfood evidence diagnostic and separate from apply readiness", () => {
    const state = makeState({
      artifact_index: [],
      tasks: {
        task_a: task("task_a", { phase_timings: [] })
      }
    });

    const projection = projectOperationalMaturityFromState({ state, events: eventsFor(state.run_id) });

    expect(projection.dogfood_evidence.status).toBe("partial");
    expect(projection.dogfood_evidence.missing_reasons).toContain("artifact_index missing");
    expect(projection.apply_readiness).toMatchObject({
      status: "ready",
      source: "run_state_v2"
    });
    expect(projection.next_action).toContain("Run a dogfood check");
  });

  test("explains runtime cost with serial barriers and verification hotspots", () => {
    const state = makeState({
      safe_waves: [
        {
          wave_id: "wave_1",
          ready: ["task_a"],
          concurrency: 1,
          timing: {
            started: "2026-05-22T10:00:00.000Z",
            completed: "2026-05-22T10:00:03.000Z",
            duration_ms: 3000
          },
          withheld: [{ task_id: "task_b", reason: "file_claim_conflict", detail: "shared.txt" }]
        },
        {
          wave_id: "wave_2",
          ready: ["task_b"],
          concurrency: 1,
          timing: {
            started: "2026-05-22T10:00:03.000Z",
            completed: "2026-05-22T10:00:09.000Z",
            duration_ms: 6000
          },
          withheld: []
        }
      ],
      tasks: {
        task_a: task("task_a"),
        task_b: task("task_b", {
          file_claims: [{ path: "shared.txt", mode: "owned" }],
          phase_timings: [
            { phase: "provider", started: "2026-05-22T10:00:03.000Z", completed: "2026-05-22T10:00:04.000Z", duration_ms: 1000 },
            { phase: "verification", started: "2026-05-22T10:00:04.000Z", completed: "2026-05-22T10:00:08.000Z", duration_ms: 4000 },
            { phase: "checkpoint", started: "2026-05-22T10:00:08.000Z", completed: "2026-05-22T10:00:08.500Z", duration_ms: 500 },
            { phase: "total", started: "2026-05-22T10:00:03.000Z", completed: "2026-05-22T10:00:09.000Z", duration_ms: 6000 }
          ]
        })
      }
    });

    const projection = projectRuntimeCostFromState({ state });

    expect(projection).toMatchObject({
      schema: "waygent.runtime_cost.v1",
      estimated_wave_count: 2,
      measured_wave_count: 2,
      serial_barriers: [{ category: "file_claim", count: 1, task_ids: ["task_b"] }]
    });
    expect(projection.parallelism_score).toBe(0.5);
    expect(projection.top_hotspots[0]).toMatchObject({ phase: "wave", duration_ms: 6000 });
    expect(projection.fixed_costs.verification).toBeGreaterThanOrEqual(4500);
    expect(projection.recommended_next_actions).toContain("Inspect verification environment cost before changing provider concurrency.");
  });

  test("classifies provider readiness from process evidence without live smoke", () => {
    expect(projectProviderReadinessFromState({
      state: makeState({
        provider_profile: { provider: "codex" },
        provider_attempts: [
          providerAttempt({
            provider: "codex",
            exit_code: null,
            failure_class: "adapter_crashed",
            process: processEvidence({
              stderr: "codex failed to start: spawn codex ENOENT",
              exit_code: null
            })
          })
        ]
      })
    })).toMatchObject({
      status: "unavailable",
      recommended_next_action: "Install or fix the codex provider command, then rerun the Waygent task."
    });

    expect(projectProviderReadinessFromState({
      state: makeState({
        provider_profile: { provider: "claude" },
        provider_attempts: [
          providerAttempt({
            provider: "claude",
            exit_code: 1,
            failure_class: "adapter_crashed",
            process: processEvidence({
              stderr: "Authentication required. Please login.",
              exit_code: 1
            })
          })
        ]
      })
    })).toMatchObject({
      status: "auth_required",
      recommended_next_action: "Authenticate the claude provider outside Waygent, then rerun the task."
    });

    expect(projectProviderReadinessFromState({ state: makeState() })).toMatchObject({
      status: "ready",
      provider: "fake"
    });
  });
});

function eventsFor(runId: string): AgentLensEvent[] {
  return [
    demoEvent({
      event_id: `event_${runId}_1`,
      agentlens_run_id: runId,
      orchestrator_run_id: runId,
      event_type: "platform.run_started",
      occurred_at: "2026-05-22T10:00:00.000Z",
      sequence: 1,
      phase: "platform",
      outcome: "running",
      summary: "Run opened."
    }),
    demoEvent({
      event_id: `event_${runId}_2`,
      agentlens_run_id: runId,
      orchestrator_run_id: runId,
      event_type: "lens.trust_report_updated",
      occurred_at: "2026-05-22T10:00:06.000Z",
      sequence: 2,
      phase: "lens",
      outcome: "success",
      summary: "Trust report updated."
    })
  ];
}

function makeState(overrides: Partial<WaygentRunStateV2> = {}): WaygentRunStateV2 {
  return {
    schema: "waygent.run_state.v2",
    run_id: "run_maturity",
    workspace: "/tmp/source",
    source_branch: "main",
    worktree_root: "/tmp/worktrees",
    run_root: "/tmp/run_maturity",
    artifact_root: "/tmp/run_maturity/artifacts",
    state_path: "/tmp/run_maturity/state.json",
    event_journal_path: "/tmp/run_maturity/events.jsonl",
    plan_path: null,
    spec_path: null,
    provider_profile: { provider: "fake", command: ["fake-provider"] },
    status: "completed",
    lifecycle_outcome: "finished",
    current_phase: "complete",
    tasks: {
      task_a: task("task_a")
    },
    safe_waves: [
      {
        wave_id: "wave_1",
        ready: ["task_a"],
        concurrency: 1,
        timing: {
          started: "2026-05-22T10:00:00.000Z",
          completed: "2026-05-22T10:00:06.000Z",
          duration_ms: 6000
        },
        withheld: []
      }
    ],
    provider_attempts: [providerAttempt()],
    reviews: [],
    verification: [{ verification_id: "verify_task_a_1", task_id: "task_a", status: "passed", kernel_result_ref: "artifacts/kernel/verify_task_a_1.json" }],
    recovery: [],
    artifact_index: [
      artifact("artifacts/provider/attempt_task_a_1.stdout.txt", "provider", "task_a"),
      artifact("artifacts/worker/task_a.json", "provider", "task_a"),
      artifact("artifacts/kernel/verify_task_a_1.json", "verification", "task_a"),
      artifact("artifacts/checkpoints/task_a/candidate_task_a.json", "checkpoint", "task_a"),
      artifact("artifacts/checkpoints/apply/run_maturity.patch", "combined_apply", null),
      artifact("artifacts/checkpoints/apply-dry-run.json", "combined_apply", null)
    ],
    apply: { status: "not_applied", checkpoint_ref: "artifacts/checkpoints/task_a/candidate_task_a.json" },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: {
      status: "passed",
      combined_apply_evidence: {
        status: "passed",
        checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
        patch_ref: "artifacts/checkpoints/apply/run_maturity.patch",
        evidence_ref: "artifacts/checkpoints/apply-dry-run.json"
      }
    },
    timestamps: {
      started_at: "2026-05-22T10:00:00.000Z",
      updated_at: "2026-05-22T10:00:06.000Z",
      completed_at: "2026-05-22T10:00:06.000Z"
    },
    ...overrides
  };
}

function task(id: string, overrides: Partial<WaygentRunStateV2["tasks"][string]> = {}): WaygentRunStateV2["tasks"][string] {
  return {
    id,
    status: "verified",
    risk: "low",
    dependencies: [],
    file_claims: [{ path: `${id}.txt`, mode: "owned" }],
    attempts: [`attempt_${id}_1`],
    task_packet_path: `/tmp/${id}.json`,
    task_packet_sha256: "a".repeat(64),
    unit_manifest: { allowed_write_globs: [`${id}.txt`] },
    checkpoint_refs: [`artifacts/checkpoints/${id}/candidate_${id}.json`],
    latest_failure_class: null,
    decision_packet_ref: null,
    timing: {},
    phase_timings: [
      { phase: "provider", started: "2026-05-22T10:00:00.000Z", completed: "2026-05-22T10:00:02.000Z", duration_ms: 2000 },
      { phase: "verification", started: "2026-05-22T10:00:02.000Z", completed: "2026-05-22T10:00:02.500Z", duration_ms: 500 },
      { phase: "checkpoint", started: "2026-05-22T10:00:02.500Z", completed: "2026-05-22T10:00:03.000Z", duration_ms: 500 },
      { phase: "total", started: "2026-05-22T10:00:00.000Z", completed: "2026-05-22T10:00:03.000Z", duration_ms: 3000 }
    ],
    ...overrides
  };
}

function providerAttempt(overrides: Partial<WaygentRunStateV2["provider_attempts"][number]> = {}): WaygentRunStateV2["provider_attempts"][number] {
  return {
    schema: "runway.provider_attempt.v1",
    attempt_id: "attempt_task_a_1",
    run_id: "run_maturity",
    task_id: "task_a",
    role: "implement",
    provider: "fake",
    command: ["fake-provider"],
    cwd: "/tmp/worktrees/task_a",
    stdin_ref: "artifacts/provider/attempt_task_a_1.stdin.txt",
    stdout_ref: "artifacts/provider/attempt_task_a_1.stdout.txt",
    stderr_ref: "artifacts/provider/attempt_task_a_1.stderr.txt",
    event_stream_ref: null,
    exit_code: 0,
    timed_out: false,
    started_at: "2026-05-22T10:00:00.000Z",
    completed_at: "2026-05-22T10:00:02.000Z",
    worker_result_ref: "artifacts/worker/task_a.json",
    failure_class: null,
    process: processEvidence(),
    ...overrides
  };
}

function processEvidence(overrides: Partial<NonNullable<WaygentRunStateV2["provider_attempts"][number]["process"]>> = {}): NonNullable<WaygentRunStateV2["provider_attempts"][number]["process"]> {
  return {
    stdout: "{\"status\":\"completed\"}",
    stderr: "",
    exit_code: 0,
    timed_out: false,
    started_at: "2026-05-22T10:00:00.000Z",
    completed_at: "2026-05-22T10:00:02.000Z",
    event_stream: null,
    stderr_summary: {
      total_lines: 0,
      counts: { error: 0, warning: 0, mcp: 0, plugin_manifest: 0, skill_loader: 0, other: 0 },
      samples: []
    },
    ...overrides
  };
}

function artifact(
  ref: string,
  producer_phase: NonNullable<WaygentRunStateV2["artifact_index"]>[number]["producer_phase"],
  task_id: string | null
): NonNullable<WaygentRunStateV2["artifact_index"]>[number] {
  return {
    ref,
    media_type: "application/json",
    sha256: "b".repeat(64),
    byte_length: 10,
    producer_phase,
    task_id,
    created_at: "2026-05-22T10:00:01.000Z"
  };
}
