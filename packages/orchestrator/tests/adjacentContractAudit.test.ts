import { describe, expect, test } from "bun:test";
import { auditAdjacentContracts } from "../src/adjacentContractAudit";

describe("adjacent contract audit", () => {
  test("surfaces source matching and handoff contract candidates", () => {
    const findings = auditAdjacentContracts({
      plan_markdown: "Update handoff markdown for source matching confidence and targetReliability.",
      spec_markdown: "Do not rename persisted MCP JSON fields such as sourceCandidates.",
      file_claims: [
        "fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/session/FeedbackQueueFormatter.kt"
      ]
    });

    expect(findings).toEqual([
      {
        code: "adjacent_contract_candidate",
        severity: "warning",
        message: "Trust-sensitive source matching or handoff changes should review docs/reference/source-matching.md.",
        task_id: null,
        evidence_refs: ["docs/reference/source-matching.md"]
      },
      {
        code: "adjacent_contract_candidate",
        severity: "warning",
        message: "Persisted MCP output changes should review docs/reference/output-schema.md.",
        task_id: null,
        evidence_refs: ["docs/reference/output-schema.md"]
      },
      {
        code: "adjacent_contract_candidate",
        severity: "warning",
        message: "Feedback console handoff wording changes should review docs/reference/feedback-console-contract.md.",
        task_id: null,
        evidence_refs: ["docs/reference/feedback-console-contract.md"]
      }
    ]);
  });
});
