import type { CrossPathInvariant, PolicyAck } from "./types";
import { runInvariantCheck } from "./checks";

export interface InvariantRunResult {
  invariant_id: string;
  passed: boolean;
  evidence: string;
  enforcement_mode: "deterministic" | "advisory";
}

function claimPath(claim: string): string {
  const idx = claim.indexOf(":");
  return idx < 0 ? claim : claim.slice(0, idx);
}

function intersects(paths_bound: string[], file_claims: string[]): boolean {
  const claimPaths = new Set(file_claims.map(claimPath));
  return paths_bound.some((p) => claimPaths.has(p));
}

export async function runInvariantsAgainstFileClaims(
  invariants: CrossPathInvariant[],
  file_claims: string[],
  cwd: string
): Promise<InvariantRunResult[]> {
  const out: InvariantRunResult[] = [];
  for (const inv of invariants) {
    if (!intersects(inv.paths_bound, file_claims)) continue;
    if (inv.enforcement.mode === "advisory") {
      out.push({
        invariant_id: inv.id,
        passed: true,
        evidence: `advisory: ${inv.enforcement.rationale}`,
        enforcement_mode: "advisory"
      });
      continue;
    }
    const res = await runInvariantCheck(inv.enforcement.check, cwd);
    out.push({
      invariant_id: inv.id,
      passed: res.passed,
      evidence: res.evidence,
      enforcement_mode: "deterministic"
    });
  }
  return out;
}

export interface AckValidationResult {
  missing: string[];
  unverified: string[];
}

const CONF_ORDER = { best_effort: 0, verified: 1 } as const;

export function validatePolicyAcks(
  invariants: CrossPathInvariant[],
  acks: PolicyAck[]
): AckValidationResult {
  const ackById = new Map(acks.map((a) => [a.invariant_id, a]));
  const missing: string[] = [];
  const unverified: string[] = [];
  for (const inv of invariants) {
    if (!inv.policy_ack_required) continue;
    const ack = ackById.get(inv.id);
    if (!ack) {
      missing.push(inv.id);
      continue;
    }
    if (CONF_ORDER[ack.confidence] < CONF_ORDER[inv.policy_ack_min_confidence]) {
      unverified.push(inv.id);
    }
  }
  return { missing, unverified };
}
