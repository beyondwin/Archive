import { Link } from "react-router-dom";

import type { RunRow } from "@/api/runs";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { durationOf, relativeFromNow } from "@/lib/format";

function isFalseSuccess(run: RunRow): boolean {
  return run.agent_outcome === "success" && run.eval_status === "failed";
}

function failuresLabel(run: RunRow): string {
  const explicitCount = run.failures_count ?? run.failure_count;
  if (typeof explicitCount === "number") return String(explicitCount);
  if (isFalseSuccess(run) || run.eval_status === "failed") return ">=1";
  return "0";
}

function evalTone(status: string): "success" | "danger" | "warning" | "muted" {
  if (status === "passed") return "success";
  if (status === "failed") return "danger";
  if (status === "incomplete" || status === "needs_eval") return "warning";
  return "muted";
}

export function RunListTable({ runs }: { runs: RunRow[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white">
      <Table>
        <THead>
          <TR>
            <TH>Started</TH>
            <TH>Agent</TH>
            <TH>Outcome</TH>
            <TH>Eval</TH>
            <TH>Failures</TH>
            <TH>Duration</TH>
            <TH>Run</TH>
          </TR>
        </THead>
        <TBody>
          {runs.map((run) => (
            <TR
              key={run.run_id}
              className={isFalseSuccess(run) ? "false-success-row bg-red-50" : ""}
            >
              <TD>{relativeFromNow(run.started_at)}</TD>
              <TD>
                <Badge tone="info">{run.agent_name || "unknown"}</Badge>
              </TD>
              <TD>{run.agent_outcome || "-"}</TD>
              <TD>
                <Badge tone={evalTone(run.eval_status)}>
                  {run.eval_status || "-"}
                </Badge>
              </TD>
              <TD className="font-mono text-xs text-zinc-700">{failuresLabel(run)}</TD>
              <TD>{durationOf(run.started_at, run.ended_at)}</TD>
              <TD className="font-mono text-xs text-zinc-600">
                <Link to={`/runs/${run.run_id}`} className="hover:text-sky-700">
                  {run.run_id}
                </Link>
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}
