import type { ProviderCapabilityManifest } from "@waygent/contracts";

export interface ProviderSupports {
  settings_path: boolean;
  mcp_config_path: boolean;
  session_id_first_attempt: boolean;
  reasoning: boolean;
}

declare module "@waygent/contracts" {
  interface ProviderCapabilityManifest {
    supports?: {
      settings_path: boolean;
      mcp_config_path: boolean;
      session_id_first_attempt: boolean;
      reasoning: boolean;
    };
  }
}

export const fakeCapabilityManifest: ProviderCapabilityManifest = {
  schema: "provider.capability_manifest.v1",
  provider: "fake",
  supported_modes: ["single-agent", "multi-agent", "review", "verify"],
  tool_calls: true,
  file_edits: true,
  shell: false,
  streaming: false,
  approvals: false,
  result_schema: "runway.worker_result.v1",
  supports: { settings_path: false, mcp_config_path: false, session_id_first_attempt: false, reasoning: false }
};

export const codexCapabilityManifest: ProviderCapabilityManifest = {
  schema: "provider.capability_manifest.v1",
  provider: "codex",
  supported_modes: ["single-agent", "multi-agent", "review", "verify"],
  tool_calls: true,
  file_edits: true,
  shell: true,
  streaming: true,
  approvals: true,
  result_schema: "runway.worker_result.v1",
  supports: { settings_path: false, mcp_config_path: false, session_id_first_attempt: false, reasoning: false }
};

export const claudeCapabilityManifest: ProviderCapabilityManifest = {
  schema: "provider.capability_manifest.v1",
  provider: "claude",
  supported_modes: ["single-agent", "multi-agent", "review", "verify"],
  tool_calls: true,
  file_edits: true,
  shell: true,
  streaming: true,
  approvals: false,
  result_schema: "runway.worker_result.v1",
  supports: { settings_path: true, mcp_config_path: true, session_id_first_attempt: true, reasoning: true }
};

export const acpCapabilityManifest: ProviderCapabilityManifest = {
  schema: "provider.capability_manifest.v1",
  provider: "acp",
  supported_modes: ["single-agent", "review"],
  tool_calls: true,
  file_edits: false,
  shell: false,
  streaming: true,
  approvals: false,
  result_schema: "runway.worker_result.v1",
  supports: { settings_path: false, mcp_config_path: false, session_id_first_attempt: false, reasoning: false }
};

export function providerSupportsCapabilities(provider: "codex" | "claude" | "fake" | "acp"): ProviderSupports {
  if (provider === "claude") return claudeCapabilityManifest.supports!;
  if (provider === "codex") return codexCapabilityManifest.supports!;
  if (provider === "acp") return acpCapabilityManifest.supports!;
  return fakeCapabilityManifest.supports!;
}

export function assertCapabilities(
  manifest: ProviderCapabilityManifest,
  requirements: Partial<Record<"file_edits" | "shell" | "approvals" | "streaming", boolean>>
): void {
  for (const [key, required] of Object.entries(requirements)) {
    if (required && manifest[key as keyof typeof requirements] !== true) {
      throw new Error(`${manifest.provider} does not support ${key}`);
    }
  }
}
