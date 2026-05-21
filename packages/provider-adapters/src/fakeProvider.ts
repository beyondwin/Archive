import type { WorkerResult } from "@waygent/contracts";
import { validateContract } from "@waygent/contracts";
import { fakeCapabilityManifest } from "./capabilities";
import type { AdapterRequest, ProviderAdapter, ProviderAdapterDescription } from "./types";

export class FakeProviderAdapter implements ProviderAdapter {
  readonly manifest = fakeCapabilityManifest;

  describe(): ProviderAdapterDescription {
    return {
      provider: "fake",
      execution: "deterministic",
      direct_agentlens_writes: false
    };
  }

  async run(request: AdapterRequest): Promise<WorkerResult> {
    return validateContract<WorkerResult>("runway.worker_result.v1", {
      schema: "runway.worker_result.v1",
      task_id: request.task_id,
      candidate_id: request.candidate_id,
      status: "completed",
      changed_files: request.changed_files ?? ["README.md"],
      summary: `Fake provider completed: ${request.prompt}`,
      evidence: { provider: "fake-provider", deterministic: true }
    });
  }
}
