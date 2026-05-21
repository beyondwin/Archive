import type { FailureClass, WorkerResult } from "@waygent/contracts";
import { validateContract } from "@waygent/contracts";
import type { ProcessAdapterOutput } from "./types";

export function normalizeProcessOutput(
  provider: "codex" | "claude" | "acp",
  task_id: string,
  candidate_id: string,
  output: ProcessAdapterOutput
): WorkerResult {
  if (output.exitCode !== 0) {
    return failed(task_id, candidate_id, "adapter_crashed", `${provider} exited ${output.exitCode}`);
  }
  try {
    const parsed = JSON.parse(output.stdout) as Partial<WorkerResult>;
    return validateContract<WorkerResult>("runway.worker_result.v1", {
      schema: "runway.worker_result.v1",
      task_id,
      candidate_id,
      status: parsed.status ?? "completed",
      changed_files: parsed.changed_files ?? [],
      summary: parsed.summary ?? `${provider} completed`,
      evidence: { provider, native: parsed.evidence ?? parsed }
    });
  } catch {
    return failed(task_id, candidate_id, "malformed_result", `${provider} produced malformed output`);
  }
}

export function failed(task_id: string, candidate_id: string, failure_class: FailureClass, summary: string): WorkerResult {
  return validateContract<WorkerResult>("runway.worker_result.v1", {
    schema: "runway.worker_result.v1",
    task_id,
    candidate_id,
    status: "failed",
    changed_files: [],
    summary,
    evidence: { failure_class },
    failure_class
  });
}
