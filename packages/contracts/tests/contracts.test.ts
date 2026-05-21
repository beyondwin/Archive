import { describe, expect, test } from "bun:test";
import {
  ContractValidationError,
  assertWaygentId,
  validateContract,
  type AgentLensEvent,
  type KernelExecutionRequest,
  type WorkerResult
} from "../src";

const event: AgentLensEvent = {
  schema: "agentlens.event.v3",
  event_id: "event_demo",
  agentlens_run_id: "run_lens",
  orchestrator_run_id: "run_orchestrator",
  producer: { name: "agentrunway", kind: "orchestrator", version: "0.1.0" },
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
});
