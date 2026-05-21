import { validateContract, type WorkerResult } from "@waygent/contracts";
import { claudeCapabilityManifest } from "./capabilities";
import type { AdapterRequest, ProviderAdapter, ProviderAdapterDescription } from "./types";

export class ClaudeProviderAdapter implements ProviderAdapter {
  readonly manifest = claudeCapabilityManifest;

  constructor(private readonly options: { executable: string } = { executable: "claude" }) {}

  describe(): ProviderAdapterDescription {
    return {
      provider: "claude",
      execution: "process",
      direct_agentlens_writes: false
    };
  }

  async run(request: AdapterRequest): Promise<WorkerResult> {
    return validateContract<WorkerResult>("runway.worker_result.v1", {
      schema: "runway.worker_result.v1",
      task_id: request.task_id,
      candidate_id: request.candidate_id,
      status: "blocked",
      changed_files: request.changed_files ?? [],
      summary: `Claude provider requires process execution wiring: ${this.options.executable}`,
      evidence: { provider: "claude", process_boundary: true },
      failure_class: "needs_infra_fix"
    });
  }
}
