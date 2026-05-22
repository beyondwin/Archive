import type { WorkerResult } from "@waygent/contracts";
import { validateContract } from "@waygent/contracts";
import { fakeCapabilityManifest } from "./capabilities";
import type { AdapterRequest, ProviderAdapter, ProviderAdapterDescription, ProviderAdapterRunResult } from "./types";

export class FakeProviderAdapter implements ProviderAdapter {
  readonly manifest = fakeCapabilityManifest;

  describe(): ProviderAdapterDescription {
    return {
      provider: "fake",
      execution: "deterministic",
      direct_agentlens_writes: false
    };
  }

  async run(request: AdapterRequest): Promise<ProviderAdapterRunResult> {
    const startedAt = new Date().toISOString();
    const worker = validateContract<WorkerResult>("runway.worker_result.v1", {
      schema: "runway.worker_result.v1",
      task_id: request.task_id,
      candidate_id: request.candidate_id,
      status: "completed",
      changed_files: request.changed_files ?? ["README.md"],
      summary: `Fake provider completed: ${request.prompt}`,
      evidence: { provider: "fake-provider", deterministic: true }
    });
    return {
      worker,
      metadata: {
        actual_model: { model: "fake", reasoning: null, source: "fake_provider" },
        usage: { input_tokens: 0, output_tokens: 0, cached_read_tokens: 0, cached_write_tokens: 0 },
        usage_source: "provider_json"
      },
      process: {
        stdout: "",
        stderr: "",
        exit_code: 0,
        timed_out: false,
        started_at: startedAt,
        completed_at: new Date().toISOString(),
        event_stream: null
      }
    };
  }
}
