import type { TrustReport } from "@/api/runs";
import { Badge } from "@/components/ui/badge";

function verdictTone(
  verdict: TrustReport["trust_verdict"],
): "success" | "warning" | "danger" | "muted" {
  if (verdict === "trusted") return "success";
  if (verdict === "untrusted" || verdict === "blocked") return "danger";
  if (verdict === "partially_trusted" || verdict === "degraded") return "warning";
  return "muted";
}

export function TrustReportPanel({ report }: { report?: TrustReport | null }) {
  if (!report) {
    return (
      <div className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-500">
        No trust report.
      </div>
    );
  }
  const issueCount =
    report.blocking_evidence.length +
    report.missing_evidence.length +
    report.projection_issues.length;

  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={verdictTone(report.trust_verdict)}>
          {report.trust_verdict}
        </Badge>
        <Badge tone="info">{report.evidence_strength}</Badge>
        <span className="font-mono text-xs text-zinc-500">
          {report.agentrunway_run_id ?? report.run_id}
        </span>
      </div>
      <div className="mt-3 grid gap-3 text-sm md:grid-cols-3">
        <div>
          <div className="text-xs text-zinc-500">Claimed outcome</div>
          <div className="mt-1 font-medium text-zinc-900">
            {report.claimed_outcome}
          </div>
        </div>
        <div>
          <div className="text-xs text-zinc-500">Evidence issues</div>
          <div className="mt-1 font-medium text-zinc-900">{issueCount}</div>
        </div>
        <div>
          <div className="text-xs text-zinc-500">Operator actions</div>
          <div className="mt-1 font-medium text-zinc-900">
            {report.operator_actions.length}
          </div>
        </div>
      </div>
    </section>
  );
}
