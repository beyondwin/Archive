import { validateContract, type WorkerResult } from "@waygent/contracts";
import { codexCapabilityManifest } from "./capabilities";
import type { AdapterRequest, ProviderAdapter, ProviderAdapterDescription } from "./types";

export class CodexProviderAdapter implements ProviderAdapter {
  readonly manifest = codexCapabilityManifest;

  constructor(private readonly options: { executable: string } = { executable: "codex" }) {}

  describe(): ProviderAdapterDescription {
    return {
      provider: "codex",
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
      summary: `Codex provider requires process execution wiring: ${this.options.executable}`,
      evidence: { provider: "codex", process_boundary: true },
      failure_class: "needs_infra_fix"
    });
  }
}
