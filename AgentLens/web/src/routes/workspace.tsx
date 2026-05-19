import { useParams } from "react-router-dom";

import { useWorkspace } from "@/api/workspaces";
import { RunListTable } from "@/components/run-list-table";

export function WorkspaceRoute() {
  const { wsId } = useParams();
  const workspace = useWorkspace(wsId);

  if (workspace.isLoading) return <div className="p-6 text-sm">Loading workspace...</div>;
  if (workspace.error || !workspace.data) {
    return <div className="p-6 text-sm text-red-700">Workspace not found.</div>;
  }

  const passRate = workspace.data.eval_pass_rate_30d;
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold text-zinc-950">
        {workspace.data.workspace_short || workspace.data.workspace_id}
      </h1>
      <div className="mt-1 text-sm text-zinc-500">
        {workspace.data.id_basis} · {workspace.data.run_count} runs · pass rate{" "}
        {passRate === null ? "-" : `${Math.round(passRate * 100)}%`}
      </div>
      <div className="mt-5">
        <RunListTable runs={workspace.data.recent_runs} />
      </div>
    </div>
  );
}
