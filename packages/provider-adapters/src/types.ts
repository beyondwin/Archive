import type { ProviderCapabilityManifest, WorkerResult } from "@waygent/contracts";

export interface AdapterRequest {
  task_id: string;
  candidate_id: string;
  prompt: string;
  changed_files?: string[];
}

export interface ProviderAdapter {
  manifest: ProviderCapabilityManifest;
  run(request: AdapterRequest): Promise<WorkerResult>;
}

export interface ProcessAdapterOutput {
  exitCode: number;
  stdout: string;
  stderr: string;
}
