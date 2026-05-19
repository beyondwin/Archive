import { Activity, Boxes, CircleDot, Gauge } from "lucide-react";
import { NavLink } from "react-router-dom";

import { useWorkspaces } from "@/api/workspaces";
import { DoctorFooter } from "@/components/doctor-footer";
import { cn } from "@/lib/cn";

export function Sidebar() {
  const workspaces = useWorkspaces();
  return (
    <aside className="flex w-72 shrink-0 flex-col bg-zinc-950 px-4 py-4 text-zinc-200">
      <div className="flex items-center gap-2 px-2">
        <div className="grid h-8 w-8 place-items-center rounded bg-sky-400 text-zinc-950">
          <Gauge aria-hidden className="h-4 w-4" />
        </div>
        <div>
          <div className="text-sm font-semibold text-white">AgentLens</div>
          <div className="text-[11px] text-zinc-400">local viewer</div>
        </div>
      </div>

      <nav className="mt-6 flex flex-col gap-1">
        <NavLink
          to="/"
          className={({ isActive }) =>
            cn(
              "flex items-center gap-2 rounded-md px-2 py-2 text-sm text-zinc-300 hover:bg-zinc-800",
              isActive && "bg-zinc-800 text-white",
            )
          }
        >
          <Activity aria-hidden className="h-4 w-4" />
          Runs
        </NavLink>
        <NavLink
          to="/empty"
          className={({ isActive }) =>
            cn(
              "flex items-center gap-2 rounded-md px-2 py-2 text-sm text-zinc-300 hover:bg-zinc-800",
              isActive && "bg-zinc-800 text-white",
            )
          }
        >
          <Boxes aria-hidden className="h-4 w-4" />
          Empty State
        </NavLink>
      </nav>

      <div className="mt-6">
        <div className="px-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
          Workspaces
        </div>
        <div className="mt-2 flex flex-col gap-1">
          {(workspaces.data ?? []).slice(0, 8).map((workspace) => (
            <NavLink
              key={workspace.workspace_id}
              to={`/workspaces/${workspace.workspace_id}`}
              className={({ isActive }) =>
                cn(
                  "flex items-center justify-between rounded-md px-2 py-2 text-xs text-zinc-300 hover:bg-zinc-800",
                  isActive && "bg-zinc-800 text-white",
                )
              }
            >
              <span className="flex min-w-0 items-center gap-2">
                <CircleDot aria-hidden className="h-3 w-3 shrink-0 text-sky-300" />
                <span className="truncate">{workspace.workspace_short}</span>
              </span>
              <span className="text-zinc-500">{workspace.run_count}</span>
            </NavLink>
          ))}
        </div>
      </div>

      <div className="mt-auto border-t border-zinc-800 pt-3">
        <DoctorFooter />
      </div>
    </aside>
  );
}
