import { ExternalLink } from "lucide-react";

import type { Failure } from "@/api/runs";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

function severityTone(severity?: string): "danger" | "warning" | "muted" {
  if (severity === "critical" || severity === "high") return "danger";
  if (severity === "medium") return "warning";
  return "muted";
}

export function FailuresPanel({
  failures,
  onEvidenceClick,
}: {
  failures: Failure[];
  onEvidenceClick?: (sha: string) => void;
}) {
  if (failures.length === 0) {
    return <div className="text-sm text-zinc-500">No failures.</div>;
  }
  return (
    <div className="flex flex-col gap-3">
      {failures.map((failure, index) => (
        <article
          key={`${failure.category}-${index}`}
          className={cn(
            "rounded-md border p-3",
            severityTone(failure.severity) === "danger" &&
              "border-red-200 bg-red-50",
            severityTone(failure.severity) === "warning" &&
              "border-amber-200 bg-amber-50",
            severityTone(failure.severity) === "muted" &&
              "border-zinc-200 bg-zinc-50",
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={severityTone(failure.severity)}>
              {(failure.severity ?? "unknown").toUpperCase()}
            </Badge>
            <code className="text-xs text-zinc-700">{failure.category}</code>
            {failure.confidence !== undefined && failure.confidence !== null && (
              <span className="text-xs text-zinc-500">
                confidence {failure.confidence}
              </span>
            )}
            {failure.blame_scope && (
              <span className="text-xs text-zinc-500">blame: {failure.blame_scope}</span>
            )}
            {failure.recoverability && (
              <span className="text-xs text-zinc-500">
                recovery: {failure.recoverability}
              </span>
            )}
          </div>
          {failure.summary && <div className="mt-2 text-sm">{failure.summary}</div>}
          {failure.evidence && failure.evidence.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-zinc-600">
              {failure.evidence.map((evidence) => (
                <button
                  key={evidence}
                  type="button"
                  className="inline-flex items-center gap-1 rounded bg-white px-2 py-1 font-mono text-sky-700 ring-1 ring-zinc-200 hover:bg-sky-50"
                  onClick={() => onEvidenceClick?.(evidence)}
                >
                  <ExternalLink aria-hidden className="h-3 w-3" />
                  {evidence}
                </button>
              ))}
            </div>
          )}
        </article>
      ))}
    </div>
  );
}
