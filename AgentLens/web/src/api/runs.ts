import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { getJson, getNdjson } from "./client";

export type ModelUsageRow = {
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
};

export type UsageProjection = {
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  cost_usd: number | null;
  pricing_source: string;
  confidence: "exact" | "estimated" | "unknown";
  model_breakdown: ModelUsageRow[];
};

export type ImportState = "full" | "partial" | "skipped";

export type TrustReport = {
  schema: "agentlens.trust_report.v1";
  run_id: string;
  agentrunway_run_id: string | null;
  claimed_outcome: string;
  trust_verdict: "trusted" | "partially_trusted" | "untrusted" | "blocked" | "degraded";
  evidence_strength: "strong" | "adequate" | "weak" | "insufficient";
  blocking_evidence: Array<Record<string, unknown>>;
  missing_evidence: Array<Record<string, unknown>>;
  residual_risks: Array<Record<string, unknown>>;
  operator_actions: Array<Record<string, unknown>>;
  projection_issues: Array<Record<string, unknown>>;
};

export type RunRow = {
  run_id: string;
  workspace_id: string;
  parent_run_id: string | null;
  started_at: string;
  ended_at: string;
  agent_name: string;
  agent_mode: string;
  recording_mode: string;
  agent_outcome: string;
  eval_status: string;
  sealed_phase: string;
  // task_18: importer-artifact projections. ``null`` for container runs that
  // have no ``artifacts/{import_report,usage}.json``.
  display_title: string | null;
  usage: UsageProjection | null;
  import_state: ImportState | null;
  trust_report?: TrustReport | null;
  failures_count?: number | null;
  failure_count?: number | null;
};

export type Failure = {
  run_id?: string;
  workspace_id?: string;
  category?: string;
  severity?: string;
  source?: string;
  blame_scope?: string;
  summary?: string;
  confidence?: number | null;
  recoverability?: string;
  evidence?: string[];
};

export type Risk = {
  run_id?: string;
  workspace_id?: string;
  category?: string;
  source?: string;
  severity?: string;
  summary?: string;
};

export type RunArtifact = {
  path?: string;
  sha256?: string;
  downloadable?: boolean;
};

export type RunDetail = {
  run_id: string;
  agent: string;
  agent_name?: string;
  agent_mode?: string;
  started_at: string;
  ended_at?: string;
  agent_outcome: string;
  eval_status: string;
  sealed_phase: string;
  workspace_id: string;
  workspace_short: string;
  summary?: string;
  // task_18: importer-artifact projections. ``null`` for container runs.
  display_title: string | null;
  usage: UsageProjection | null;
  import_state: ImportState | null;
  trust_report?: TrustReport | null;
  failures: Failure[];
  risks: Risk[];
  artifacts?: RunArtifact[];
  partial?: boolean;
  manifest_seal?: {
    phase?: string;
    sealed_at?: string;
    manifest_digest?: string;
    integrity?: string;
    mismatches_count?: number;
  };
};

export type RunsFilters = {
  workspace_id?: string;
  agent?: string;
  eval_status?: string;
  agent_outcome?: string;
  since_days?: number;
};

type RunsPage = { items: RunRow[]; next_cursor: string | null };

function runsUrl(filters: RunsFilters, cursor?: string | null): string {
  const params = new URLSearchParams();
  params.set("limit", "50");
  if (cursor) params.set("cursor", cursor);
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const query = params.toString();
  return `/api/v1/runs${query ? `?${query}` : ""}`;
}

export function useRuns(filters: RunsFilters) {
  return useInfiniteQuery({
    queryKey: ["runs", filters],
    queryFn: ({ pageParam }) => getJson<RunsPage>(runsUrl(filters, pageParam)),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => getJson<RunDetail>(`/api/v1/runs/${runId}`),
    enabled: Boolean(runId),
  });
}

export function useRunEvents(runId: string | undefined) {
  return useQuery({
    queryKey: ["run-events", runId],
    queryFn: () => getNdjson(`/api/v1/runs/${runId}/events`),
    enabled: Boolean(runId),
  });
}

export function useRunFailures(runId: string | undefined) {
  return useQuery({
    queryKey: ["run-failures", runId],
    queryFn: () => getJson<Failure[]>(`/api/v1/runs/${runId}/failures`),
    enabled: Boolean(runId),
  });
}

export function useRunArtifacts(runId: string | undefined) {
  return useQuery({
    queryKey: ["run-artifacts", runId],
    queryFn: () => getJson<RunArtifact[]>(`/api/v1/runs/${runId}/artifacts`),
    enabled: Boolean(runId),
  });
}
