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
            event_stream: null
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
      timestamps: {
        started_at: "2026-05-21T00:00:00Z",
        updated_at: "2026-05-21T00:00:02Z",
        completed_at: "2026-05-21T00:00:02Z"
      }
    };

    expect(validateContract("waygent.run_state.v2", state)).toEqual(state);
  });
});
