import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TranscriptView } from "./transcript-view";

describe("TranscriptView", () => {
  it("renders event numbers, type badges, and compact payloads", () => {
    render(
      <TranscriptView
        events={[
          {
            type: "command.finished",
            command: "npm test",
            exit_code: 1,
            evidence_sha: "sha256:abc123",
          },
        ]}
      />,
    );

    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("command.finished")).toBeInTheDocument();
    expect(screen.getByText(/"command":"npm test"/)).toBeInTheDocument();
    expect(screen.getByText(/"exit_code":1/)).toBeInTheDocument();
  });

  it("marks events containing the selected evidence sha", () => {
    const { container } = render(
      <TranscriptView
        highlightSha="sha256:abc123"
        events={[
          { type: "command.started", command: "npm test" },
          {
            type: "command.finished",
            command: "npm test",
            evidence_sha: "sha256:abc123",
          },
        ]}
      />,
    );

    const highlighted = container.querySelector(".bg-yellow-50");
    expect(highlighted).not.toBeNull();
    expect(highlighted).toHaveTextContent("sha256:abc123");
  });

  it("surfaces unparseable transcript lines", () => {
    render(<TranscriptView events={[{ _error: "parse", line: 7 }]} />);

    expect(screen.getByText("unparseable line 7")).toBeInTheDocument();
  });
});
