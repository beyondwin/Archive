import { useQuery } from "@tanstack/react-query";

import type { RunRow } from "./runs";
import { getJson } from "./client";

export type WorkspaceSummary = {
  workspace_id: string;
  workspace_short: string;
  id_basis: string;
  run_count: number;
  latest_started_at: string | null;
};

export type WorkspaceDetail = WorkspaceSummary & {
  recent_runs: RunRow[];
  eval_pass_rate_30d: number | null;
  agent_breakdown: Record<string, number>;
};

export function useWorkspaces() {
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: () => getJson<WorkspaceSummary[]>("/api/v1/workspaces"),
  });
}

export function useWorkspace(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["workspace", workspaceId],
    queryFn: () => getJson<WorkspaceDetail>(`/api/v1/workspaces/${workspaceId}`),
    enabled: Boolean(workspaceId),
  });
}
