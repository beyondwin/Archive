import type { ProviderCapabilityManifest, WorkerResult } from "@waygent/contracts";

export type ProviderExecutionBoundary = "deterministic" | "process";

export interface ProviderAdapterDescription {
  provider: "fake" | "codex" | "claude";
  execution: ProviderExecutionBoundary;
  direct_agentlens_writes: false;
}

export interface AdapterRequest {
  task_id: string;
  candidate_id: string;
  prompt: string;
  changed_files?: string[];
}

export interface ProviderAdapter {
  manifest: ProviderCapabilityManifest;
  describe(): ProviderAdapterDescription;
  run(request: AdapterRequest): Promise<WorkerResult>;
}

export interface ProcessAdapterOutput {
  exitCode: number;
  stdout: string;
  stderr: string;
}
