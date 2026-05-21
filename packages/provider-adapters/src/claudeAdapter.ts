import type { WorkerResult } from "@waygent/contracts";
import { claudeCapabilityManifest } from "./capabilities";
import { runProviderProcess } from "./processAdapters";
import type { AdapterRequest, ProviderAdapter, ProviderAdapterDescription, ProviderProcessOptions } from "./types";

export class ClaudeProviderAdapter implements ProviderAdapter {
  readonly manifest = claudeCapabilityManifest;

  constructor(private readonly options: ProviderProcessOptions = { executable: "claude", args: ["-p", "--output-format", "json"] }) {}

  describe(): ProviderAdapterDescription {
    return {
      provider: "claude",
      execution: "process",
      direct_agentlens_writes: false
    };
  }

  async run(request: AdapterRequest): Promise<WorkerResult> {
    return runProviderProcess("claude", request, this.options);
  }
}
