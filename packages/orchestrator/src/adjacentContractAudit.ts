import type { IntakeFinding } from "@waygent/contracts";

export interface AdjacentContractAuditInput {
  plan_markdown: string;
  spec_markdown: string;
  file_claims: string[];
}

export function auditAdjacentContracts(input: AdjacentContractAuditInput): IntakeFinding[] {
  const haystack = [
    input.plan_markdown,
    input.spec_markdown,
    input.file_claims.join("\n")
  ].join("\n").toLowerCase();
  const findings: IntakeFinding[] = [];
  if (/(source matching|sourcecandidate|source candidate|targetreliability|confidence|handoff)/.test(haystack)) {
    findings.push(finding(
      "Trust-sensitive source matching or handoff changes should review docs/reference/source-matching.md.",
      "docs/reference/source-matching.md"
    ));
  }
  if (/(persisted mcp json|output schema|sourcecandidates|targetreliability|items|screens|itemid|screenid)/.test(haystack)) {
    findings.push(finding(
      "Persisted MCP output changes should review docs/reference/output-schema.md.",
      "docs/reference/output-schema.md"
    ));
  }
  if (/(feedback console|copy prompt|compact|handoff markdown|feedbackqueueformatter|compacthandoffrenderer)/.test(haystack)) {
    findings.push(finding(
      "Feedback console handoff wording changes should review docs/reference/feedback-console-contract.md.",
      "docs/reference/feedback-console-contract.md"
    ));
  }
  return findings;
}

function finding(message: string, ref: string): IntakeFinding {
  return {
    code: "adjacent_contract_candidate",
    severity: "warning",
    message,
    task_id: null,
    evidence_refs: [ref]
  };
}
