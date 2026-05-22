import type { RiskLevel } from "@waygent/contracts";

export interface RiskInferenceInput {
  title: string;
  body: string;
  file_claims: ReadonlyArray<{ path: string; mode?: string }>;
}

export interface RiskInferenceResult {
  risk: RiskLevel;
  reason: string;
  matched_signals: string[];
}

const HIGH_KEYWORDS = /\b(schema migration|database migration|public api|breaking change|production deploy|secrets?|credentials?|auth(?:entication)?)\b/i;
const HIGH_PATHS = /(migration|schema|public-api|production|secrets?)/i;
const HIGH_CLAIM_COUNT = 10;

export function inferRiskLevel(input: RiskInferenceInput): RiskInferenceResult {
  const signals: string[] = [];
  const haystack = `${input.title}\n${input.body}`;
  const keywordMatch = haystack.match(HIGH_KEYWORDS);
  if (keywordMatch) {
    signals.push(`keyword:${keywordMatch[0].toLowerCase()}`);
    return {
      risk: "high",
      reason: "high-risk keyword match",
      matched_signals: ["high_keyword", ...signals]
    };
  }

  if (input.file_claims.length > HIGH_CLAIM_COUNT) {
    signals.push(`claim_count:${input.file_claims.length}`);
    return {
      risk: "high",
      reason: "high file_claim count or sensitive path",
      matched_signals: ["high_claim_count", ...signals]
    };
  }
  for (const claim of input.file_claims) {
    const pathMatch = claim.path.match(HIGH_PATHS);
    if (pathMatch) {
      signals.push(`path:${pathMatch[0].toLowerCase()}`);
      return {
        risk: "high",
        reason: "high file_claim count or sensitive path",
        matched_signals: ["high_sensitive_path", ...signals]
      };
    }
  }

  const topDirs = new Set<string>();
  for (const claim of input.file_claims) {
    const head = claim.path.split("/")[0];
    if (head) topDirs.add(head);
  }
  if (topDirs.size > 1) {
    return {
      risk: "medium",
      reason: "cross-package claims",
      matched_signals: ["cross_package", `top_dirs:${topDirs.size}`]
    };
  }

  return {
    risk: "low",
    reason: "single-package, no risk keyword",
    matched_signals: ["default_low"]
  };
}
