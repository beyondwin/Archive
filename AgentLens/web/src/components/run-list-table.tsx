import { Link } from "react-router-dom";

import type { ImportState, RunRow, UsageProjection } from "@/api/runs";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { durationOf, relativeFromNow } from "@/lib/format";

const EM_DASH = "—";

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

function trustTone(
  verdict?: string,
): "success" | "danger" | "warning" | "info" | "muted" {
  if (verdict === "trusted") return "success";
  if (verdict === "untrusted" || verdict === "blocked") return "danger";
  if (verdict === "partially_trusted" || verdict === "degraded") return "warning";
  return "muted";
}

function titleLabel(run: RunRow): string {
  if (run.display_title && run.display_title.trim().length > 0) {
    return run.display_title;
  }
  // Fallback: short prefix of run_id (first 12 chars covers run_YYYYMMDD).
  return run.run_id.slice(0, 12);
}

function usageLabel(usage: UsageProjection | null | undefined): string {
  if (!usage) return EM_DASH;
  return `${usage.input_tokens} / ${usage.output_tokens}`;
}

function costLabel(usage: UsageProjection | null | undefined): string {
  if (!usage || typeof usage.cost_usd !== "number") return EM_DASH;
  return `$${usage.cost_usd.toFixed(2)}`;
}

function confidenceTone(
  confidence: UsageProjection["confidence"],
): "success" | "info" | "muted" {
  if (confidence === "exact") return "success";
  if (confidence === "estimated") return "info";
  return "muted";
}

function importStateTone(
  state: ImportState,
): "success" | "warning" | "danger" {
  if (state === "full") return "success";
  if (state === "partial") return "warning";
  return "danger";
}

export function RunListTable({ runs }: { runs: RunRow[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white">
      <Table>
        <THead>
          <TR>
            <TH>Started</TH>
            <TH>Agent</TH>
            <TH>Title</TH>
            <TH>Outcome</TH>
            <TH>Eval</TH>
            <TH>Trust</TH>
            <TH>Failures</TH>
            <TH>Usage</TH>
            <TH>Cost</TH>
            <TH>Confidence</TH>
            <TH>Import</TH>
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
              <TD className="max-w-[20rem] truncate text-zinc-800">
                {titleLabel(run)}
              </TD>
              <TD>{run.agent_outcome || "-"}</TD>
              <TD>
                <Badge tone={evalTone(run.eval_status)}>
                  {run.eval_status || "-"}
                </Badge>
              </TD>
              <TD>
                {run.trust_report ? (
                  <Badge tone={trustTone(run.trust_report.trust_verdict)}>
                    {run.trust_report.trust_verdict}
                  </Badge>
                ) : (
                  <span className="text-xs text-zinc-400">{EM_DASH}</span>
                )}
              </TD>
              <TD className="font-mono text-xs text-zinc-700">{failuresLabel(run)}</TD>
              <TD className="font-mono text-xs text-zinc-700">
                {usageLabel(run.usage)}
              </TD>
              <TD className="font-mono text-xs text-zinc-700">
                {costLabel(run.usage)}
              </TD>
              <TD>
                {run.usage ? (
                  <Badge tone={confidenceTone(run.usage.confidence)}>
                    {run.usage.confidence}
                  </Badge>
                ) : (
                  <span className="text-xs text-zinc-400">{EM_DASH}</span>
                )}
              </TD>
              <TD>
                {run.import_state ? (
                  <Badge tone={importStateTone(run.import_state)}>
                    {run.import_state}
                  </Badge>
                ) : (
                  <span className="text-xs text-zinc-400">{EM_DASH}</span>
                )}
              </TD>
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
