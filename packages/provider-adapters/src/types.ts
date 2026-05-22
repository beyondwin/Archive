import type { ModelAttestation, ProviderCapabilityManifest, ProviderRole, TokenUsage, UsageSource, WorkerResult } from "@waygent/contracts";

export type ProviderExecutionBoundary = "deterministic" | "process";

export interface ProviderAdapterDescription {
  provider: "fake" | "codex" | "claude";
  execution: ProviderExecutionBoundary;
  direct_agentlens_writes: false;
}

export interface AdapterRequest {
  task_id: string;
  candidate_id: string;
  role?: ProviderRole;
  prompt: string;
  task_packet_path?: string;
  cwd?: string;
  changed_files?: string[];
}

export interface ProviderProcessOptions {
  executable: string;
  args?: string[];
  cwd?: string;
  env?: Record<string, string>;
  timeout_ms?: number;
  model?: string;
  effort?: string;
}

export interface ProviderAdapterRunResult {
  worker: WorkerResult;
  process: {
    stdout: string;
    stderr: string;
    exit_code: number | null;
    timed_out: boolean;
    started_at: string;
    completed_at: string | null;
    event_stream: string | null;
  };
  metadata?: ProviderRunMetadata;
}

export interface ProviderRunMetadata {
  actual_model: ModelAttestation;
  usage: TokenUsage | null;
  usage_source: UsageSource;
}

export interface ProviderAdapter {
  manifest: ProviderCapabilityManifest;
  describe(): ProviderAdapterDescription;
  run(request: AdapterRequest): Promise<ProviderAdapterRunResult>;
}

export interface ProcessAdapterOutput {
  exitCode: number | null;
  stdout: string;
  stderr: string;
  timedOut?: boolean;
  startedAt?: string;
  completedAt?: string | null;
  eventStream?: string | null;
}
