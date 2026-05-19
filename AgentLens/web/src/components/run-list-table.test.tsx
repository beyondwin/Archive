import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { RunListTable } from "./run-list-table";

describe("RunListTable", () => {
  it("highlights false-success rows", () => {
    render(
      <MemoryRouter>
        <RunListTable
          runs={[
            {
              run_id: "run_false_success",
              workspace_id: "ws_demo",
              parent_run_id: null,
              started_at: "2026-01-01T00:00:00Z",
              ended_at: "2026-01-01T00:00:05Z",
              agent_name: "generic",
              agent_mode: "cli",
              recording_mode: "minimal",
              agent_outcome: "success",
              eval_status: "failed",
              sealed_phase: "final",
              display_title: null,
              usage: null,
              import_state: null,
            },
          ]}
        />
      </MemoryRouter>,
    );
    const row = screen.getByText("run_false_success").closest("tr");
    expect(row).toHaveClass("false-success-row");
  });

  it("shows API failure counts when present", () => {
    render(
      <MemoryRouter>
        <RunListTable
          runs={[
            {
              run_id: "run_with_failures",
              workspace_id: "ws_demo",
              parent_run_id: null,
              started_at: "2026-01-01T00:00:00Z",
              ended_at: "2026-01-01T00:00:05Z",
              agent_name: "generic",
              agent_mode: "cli",
              recording_mode: "minimal",
              agent_outcome: "failure",
              eval_status: "failed",
              sealed_phase: "final",
              failures_count: 3,
              display_title: null,
              usage: null,
              import_state: null,
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("columnheader", { name: "Failures" })).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("derives at least one failure for false-success rows without a count", () => {
    render(
      <MemoryRouter>
        <RunListTable
          runs={[
            {
              run_id: "run_false_success",
              workspace_id: "ws_demo",
              parent_run_id: null,
              started_at: "2026-01-01T00:00:00Z",
              ended_at: "2026-01-01T00:00:05Z",
              agent_name: "generic",
              agent_mode: "cli",
              recording_mode: "minimal",
              agent_outcome: "success",
              eval_status: "failed",
              sealed_phase: "final",
              display_title: null,
              usage: null,
              import_state: null,
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText(">=1")).toBeInTheDocument();
  });

  it("derives at least one failure for failed eval rows without a count", () => {
    render(
      <MemoryRouter>
        <RunListTable
          runs={[
            {
              run_id: "run_failed_eval",
              workspace_id: "ws_demo",
              parent_run_id: null,
              started_at: "2026-01-01T00:00:00Z",
              ended_at: "2026-01-01T00:00:05Z",
              agent_name: "generic",
              agent_mode: "cli",
              recording_mode: "minimal",
              agent_outcome: "failed",
              eval_status: "failed",
              sealed_phase: "final",
              display_title: null,
              usage: null,
              import_state: null,
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText(">=1")).toBeInTheDocument();
  });
});
