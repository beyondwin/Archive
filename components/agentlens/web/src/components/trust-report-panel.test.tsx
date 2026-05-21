import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TrustReportPanel } from "./trust-report-panel";

describe("TrustReportPanel", () => {
  it("renders the trust verdict and evidence strength", () => {
    render(
      <TrustReportPanel
        report={{
          schema: "agentlens.trust_report.v1",
          run_id: "run_1",
          agentrunway_run_id: "ar-001",
          claimed_outcome: "success",
          trust_verdict: "untrusted",
          evidence_strength: "insufficient",
          blocking_evidence: [],
          missing_evidence: [{ code: "missing_verification_pass" }],
          residual_risks: [],
          operator_actions: [{ code: "rerun_verification" }],
          projection_issues: [],
        }}
      />,
    );

    expect(screen.getByText("untrusted")).toBeInTheDocument();
    expect(screen.getByText("insufficient")).toBeInTheDocument();
    expect(screen.getByText("ar-001")).toBeInTheDocument();
    expect(screen.getAllByText("1")).toHaveLength(2);
  });
});
