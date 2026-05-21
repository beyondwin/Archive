import { codexCapabilityManifest } from "./capabilities";
import { runProviderProcess } from "./processAdapters";
import type { AdapterRequest, ProviderAdapter, ProviderAdapterDescription, ProviderAdapterRunResult, ProviderProcessOptions } from "./types";

export class CodexProviderAdapter implements ProviderAdapter {
  readonly manifest = codexCapabilityManifest;

  constructor(private readonly options: ProviderProcessOptions = { executable: "codex", args: ["exec", "--json", "-"] }) {}

  describe(): ProviderAdapterDescription {
    return {
      provider: "codex",
      execution: "process",
      direct_agentlens_writes: false
    };
  }

  async run(request: AdapterRequest): Promise<ProviderAdapterRunResult> {
    return runProviderProcess("codex", request, this.options);
  }
}
