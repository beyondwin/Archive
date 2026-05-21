import { useMemo, useState } from "react";
import { Navigate } from "react-router-dom";

import { useMeta } from "@/api/meta";
import { type RunsFilters, useRuns } from "@/api/runs";
import { RunListTable } from "@/components/run-list-table";
import { Button } from "@/components/ui/button";

export function RunsListRoute() {
  const meta = useMeta();
  const [filters, setFilters] = useState<RunsFilters>({});
  const runs = useRuns(filters);
  const items = useMemo(
    () => runs.data?.pages.flatMap((page) => page.items) ?? [],
    [runs.data],
  );
  const hasActiveFilters = Object.values(filters).some(
    (value) => value !== undefined && value !== "",
  );

  function updateFilter<Key extends keyof RunsFilters>(
    key: Key,
    value: RunsFilters[Key] | undefined,
  ) {
    setFilters((current) => {
      const next = { ...current };
      if (value === undefined || value === "") {
        delete next[key];
      } else {
        next[key] = value;
      }
      return next;
    });
  }

  if (meta.data && !meta.data.store_exists) return <Navigate to="/empty" replace />;
  if (runs.isLoading && !runs.data) return <div className="p-6 text-sm">Loading runs...</div>;
  if (runs.error) {
    return <div className="p-6 text-sm text-red-700">Failed to load runs.</div>;
  }
  if (meta.data?.store_exists && runs.isSuccess && !hasActiveFilters && items.length === 0) {
    return <Navigate to="/empty" replace />;
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-950">Runs</h1>
          <p className="mt-1 text-sm text-zinc-500">
            {items.length} visible · newest first
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-[11px] font-medium text-zinc-500">
            Agent
            <input
              aria-label="Agent"
              className="h-9 w-36 rounded-md border border-zinc-300 bg-white px-2 text-sm text-zinc-900"
              placeholder="Any agent"
              value={filters.agent ?? ""}
              onChange={(event) => updateFilter("agent", event.target.value || undefined)}
            />
          </label>
          <label className="flex flex-col gap-1 text-[11px] font-medium text-zinc-500">
            Agent outcome
            <select
              aria-label="Agent outcome"
              className="h-9 w-36 rounded-md border border-zinc-300 bg-white px-2 text-sm text-zinc-900"
              value={filters.agent_outcome ?? ""}
              onChange={(event) =>
                updateFilter("agent_outcome", event.target.value || undefined)
              }
            >
              <option value="">All outcomes</option>
              <option value="success">success</option>
              <option value="failed">failed</option>
              <option value="partial">partial</option>
              <option value="unknown">unknown</option>
              <option value="cancelled">cancelled</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[11px] font-medium text-zinc-500">
            Eval status
            <select
              aria-label="Eval status"
              className="h-9 w-36 rounded-md border border-zinc-300 bg-white px-2 text-sm text-zinc-900"
              value={filters.eval_status ?? ""}
              onChange={(event) =>
                updateFilter("eval_status", event.target.value || undefined)
              }
            >
              <option value="">All evals</option>
              <option value="passed">passed</option>
              <option value="failed">failed</option>
              <option value="incomplete">incomplete</option>
              <option value="needs_eval">needs_eval</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[11px] font-medium text-zinc-500">
            Since
            <select
              aria-label="Since"
              className="h-9 w-32 rounded-md border border-zinc-300 bg-white px-2 text-sm text-zinc-900"
              value={filters.since_days?.toString() ?? ""}
              onChange={(event) =>
                updateFilter(
                  "since_days",
                  event.target.value ? Number(event.target.value) : undefined,
                )
              }
            >
              <option value="">Any time</option>
              <option value="1">1 day</option>
              <option value="7">7 days</option>
              <option value="30">30 days</option>
              <option value="90">90 days</option>
              <option value="365">365 days</option>
            </select>
          </label>
          {hasActiveFilters && (
            <Button variant="outline" onClick={() => setFilters({})}>
              Reset
            </Button>
          )}
        </div>
      </div>
      {items.length === 0 ? (
        <div className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-500">
          No runs match the current filters.
        </div>
      ) : (
        <RunListTable runs={items} />
      )}
      {runs.hasNextPage && (
        <div className="mt-4 text-center">
          <Button variant="outline" onClick={() => void runs.fetchNextPage()}>
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}
