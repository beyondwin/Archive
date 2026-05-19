import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FailuresPanel } from "./failures-panel";

describe("FailuresPanel", () => {
  it("renders an empty state when no failures are present", () => {
    render(<FailuresPanel failures={[]} />);

    expect(screen.getByText("No failures.")).toBeInTheDocument();
  });

  it("renders severity, category, confidence, blame, recovery, and summary", () => {
    render(
      <FailuresPanel
        failures={[
          {
            category: "UNACKNOWLEDGED_FAILED_COMMAND",
            severity: "medium",
            confidence: 0.82,
            blame_scope: "agent",
            recoverability: "retryable",
            summary: "command failed after claiming success",
          },
        ]}
      />,
    );

    expect(screen.getByText("MEDIUM")).toBeInTheDocument();
    expect(screen.getByText("UNACKNOWLEDGED_FAILED_COMMAND")).toBeInTheDocument();
    expect(screen.getByText("confidence 0.82")).toBeInTheDocument();
    expect(screen.getByText("blame: agent")).toBeInTheDocument();
    expect(screen.getByText("recovery: retryable")).toBeInTheDocument();
    expect(screen.getByText("command failed after claiming success")).toBeInTheDocument();
  });

  it("renders evidence buttons that can drive transcript highlighting", async () => {
    const onEvidenceClick = vi.fn();
    render(
      <FailuresPanel
        failures={[
          {
            category: "UNACKNOWLEDGED_FAILED_COMMAND",
            severity: "high",
            summary: "failed command was not acknowledged",
            evidence: ["sha256:abc123"],
          },
        ]}
        onEvidenceClick={onEvidenceClick}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /sha256:abc123/i }));
    expect(onEvidenceClick).toHaveBeenCalledWith("sha256:abc123");
  });
});
