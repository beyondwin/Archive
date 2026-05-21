import type { RiskLevel } from "@waygent/contracts";
import type { FileClaim } from "@waygent/runway-control";

export function shouldReviewTask(input: { risk: RiskLevel; file_claims: FileClaim[]; previous_failure_count: number }): boolean {
  if (input.risk === "high") return true;
  if (input.previous_failure_count > 0) return true;
  return input.file_claims.some((claim) => claim.mode === "owned" && isBroadClaim(claim.path));
}

function isBroadClaim(path: string): boolean {
  return path === "." || path === "*" || (path.split("/").length <= 1 && path.endsWith("*"));
}
