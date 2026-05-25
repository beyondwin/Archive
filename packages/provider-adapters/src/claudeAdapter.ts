import { claudeCapabilityManifest } from "./capabilities";
import { runProviderProcess } from "./processAdapters";
import type { AdapterRequest, ProviderAdapter, ProviderAdapterDescription, ProviderAdapterRunResult, ProviderProcessOptions } from "./types";

export const CLAUDE_DEFAULT_ARGS: readonly string[] = [
  "-p",
  "--output-format",
  "stream-json",
  "--include-partial-messages",
  "--verbose"
];

export class ClaudeProviderAdapter implements ProviderAdapter {
  readonly manifest = claudeCapabilityManifest;

  constructor(private readonly options: ProviderProcessOptions = { executable: "claude", args: [...CLAUDE_DEFAULT_ARGS] }) {}

  describe(): ProviderAdapterDescription {
    return {
      provider: "claude",
      execution: "process",
      direct_agentlens_writes: false
    };
  }

  async run(request: AdapterRequest): Promise<ProviderAdapterRunResult> {
    return runProviderProcess("claude", request, this.options);
  }
}
