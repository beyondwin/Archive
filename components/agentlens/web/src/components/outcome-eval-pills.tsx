import { CheckCircle2, XCircle } from "lucide-react";

import { Card, CardBody } from "@/components/ui/card";

export function OutcomeEvalPills({
  agentOutcome,
  evalStatus,
  reason,
  failureCount,
}: {
  agentOutcome?: string;
  evalStatus?: string;
  reason?: string;
  failureCount?: number;
}) {
  const success = agentOutcome === "success";
  const failed = evalStatus === "failed";
  return (
    <Card>
      <CardBody className="grid gap-5 md:grid-cols-2">
        <div className="rounded-md bg-emerald-50 p-4 ring-1 ring-emerald-100">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-emerald-800">
            Agent claims
          </div>
          <div className="mt-2 flex items-center gap-2 text-xl font-semibold text-emerald-900">
            {success ? (
              <CheckCircle2 aria-hidden className="h-5 w-5" />
            ) : (
              <XCircle aria-hidden className="h-5 w-5 text-red-700" />
            )}
            {agentOutcome ?? "unknown"}
          </div>
          {reason && <div className="mt-1 text-xs text-emerald-900">{reason}</div>}
        </div>

        <div className="rounded-md bg-red-50 p-4 ring-1 ring-red-100">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-red-800">
            Evaluator says
          </div>
          <div className="mt-2 flex items-center gap-2 text-xl font-semibold text-red-900">
            {failed ? (
              <XCircle aria-hidden className="h-5 w-5" />
            ) : (
              <CheckCircle2 aria-hidden className="h-5 w-5 text-emerald-700" />
            )}
            {evalStatus ?? "unknown"}
          </div>
          {failureCount !== undefined && failed && (
            <div className="mt-1 text-xs font-medium text-red-800">
              {failureCount} failures · discrepancy
            </div>
          )}
        </div>
      </CardBody>
    </Card>
  );
}
