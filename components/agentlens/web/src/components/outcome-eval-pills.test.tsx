import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OutcomeEvalPills } from "./outcome-eval-pills";

describe("OutcomeEvalPills", () => {
  it("makes a success-vs-failed discrepancy explicit", () => {
    render(
      <OutcomeEvalPills
        agentOutcome="success"
        evalStatus="failed"
        failureCount={1}
      />,
    );
    expect(screen.getByText(/Agent claims/i)).toBeInTheDocument();
    expect(screen.getByText(/Evaluator says/i)).toBeInTheDocument();
    expect(screen.getByText(/discrepancy/i)).toBeInTheDocument();
  });

  it("shows the agent reason without inventing a discrepancy for passing evals", () => {
    render(
      <OutcomeEvalPills
        agentOutcome="success"
        evalStatus="passed"
        reason="completed all requested checks"
        failureCount={0}
      />,
    );

    expect(screen.getByText("completed all requested checks")).toBeInTheDocument();
    expect(screen.queryByText(/discrepancy/i)).not.toBeInTheDocument();
  });

  it("falls back to unknown labels when outcome data is absent", () => {
    render(<OutcomeEvalPills />);

    expect(screen.getAllByText("unknown")).toHaveLength(2);
  });
});
