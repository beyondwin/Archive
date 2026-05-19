import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { RunRow, UsageProjection } from "@/api/runs";

import { RunListTable } from "./run-list-table";

function baseRow(overrides: Partial<RunRow> = {}): RunRow {
  return {
    run_id: "run_20260101_aaaaaa",
    workspace_id: "ws_demo",
    parent_run_id: null,
    started_at: "2026-01-01T00:00:00Z",
    ended_at: "2026-01-01T00:00:05Z",
    agent_name: "generic",
    agent_mode: "cli",
    recording_mode: "minimal",
    agent_outcome: "success",
    eval_status: "passed",
    sealed_phase: "final",
    display_title: null,
    usage: null,
    import_state: null,
    ...overrides,
  };
}

const usageExact: UsageProjection = {
  input_tokens: 1234,
  output_tokens: 567,
  cache_creation_tokens: 0,
  cache_read_tokens: 0,
  reasoning_tokens: 0,
  cost_usd: 0.4231,
  pricing_source: "anthropic-public-2026-01",
  confidence: "exact",
  model_breakdown: [],
};

describe("RunListTable", () => {
  it("highlights false-success rows", () => {
    render(
      <MemoryRouter>
        <RunListTable
          runs={[
            baseRow({
              run_id: "run_false_success",
              agent_outcome: "success",
              eval_status: "failed",
            }),
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
            baseRow({
              run_id: "run_with_failures",
              agent_outcome: "failure",
              eval_status: "failed",
              failures_count: 3,
            }),
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
            baseRow({
              run_id: "run_false_success",
              agent_outcome: "success",
              eval_status: "failed",
            }),
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
            baseRow({
              run_id: "run_failed_eval",
              agent_outcome: "failed",
              eval_status: "failed",
            }),
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText(">=1")).toBeInTheDocument();
  });

  it("renders Title/Usage/Cost/Confidence/Import-state for a fully populated row", () => {
    render(
      <MemoryRouter>
        <RunListTable
          runs={[
            baseRow({
              run_id: "run_20260101_full_populated_abc",
              display_title: "Refactor the importer",
              usage: usageExact,
              import_state: "full",
            }),
          ]}
        />
      </MemoryRouter>,
    );

    // Columns exist
    expect(screen.getByRole("columnheader", { name: "Title" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Usage" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Cost" })).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Confidence" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Import" }),
    ).toBeInTheDocument();

    // Cells populated
    expect(screen.getByText("Refactor the importer")).toBeInTheDocument();
    expect(screen.getByText("1234 / 567")).toBeInTheDocument();
    expect(screen.getByText("$0.42")).toBeInTheDocument();
    expect(screen.getByText("exact")).toBeInTheDocument();
    expect(screen.getByText("full")).toBeInTheDocument();
  });

  it("falls back to short run_id and em-dash placeholders when projections are null", () => {
    render(
      <MemoryRouter>
        <RunListTable
          runs={[
            baseRow({
              run_id: "run_20260101_nullrowxyz",
              display_title: null,
              usage: null,
              import_state: null,
            }),
          ]}
        />
      </MemoryRouter>,
    );

    const row = screen
      .getByText("run_20260101_nullrowxyz")
      .closest("tr") as HTMLElement;
    // Title fallback uses short run_id (first 12 chars)
    expect(within(row).getByText("run_20260101")).toBeInTheDocument();
    // Usage + Cost show em-dash placeholder
    const dashes = within(row).getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
    // Confidence and Import-state badges are absent for null usage / import_state
    expect(within(row).queryByText("exact")).not.toBeInTheDocument();
    expect(within(row).queryByText("estimated")).not.toBeInTheDocument();
    expect(within(row).queryByText("unknown")).not.toBeInTheDocument();
    expect(within(row).queryByText("full")).not.toBeInTheDocument();
    expect(within(row).queryByText("partial")).not.toBeInTheDocument();
    expect(within(row).queryByText("skipped")).not.toBeInTheDocument();
  });

  it("renders the partial import-state badge visually distinct from full", () => {
    render(
      <MemoryRouter>
        <RunListTable
          runs={[
            baseRow({
              run_id: "run_full_aaaa",
              import_state: "full",
            }),
            baseRow({
              run_id: "run_partial_bbbb",
              import_state: "partial",
            }),
            baseRow({
              run_id: "run_skipped_cccc",
              import_state: "skipped",
            }),
          ]}
        />
      </MemoryRouter>,
    );

    const fullBadge = screen.getByText("full");
    const partialBadge = screen.getByText("partial");
    const skippedBadge = screen.getByText("skipped");

    // Distinct classNames (different tones) — concrete tone tokens come from <Badge>
    expect(fullBadge.className).not.toEqual(partialBadge.className);
    expect(partialBadge.className).not.toEqual(skippedBadge.className);
    // Partial is visually flagged (amber tone in our Badge component)
    expect(partialBadge.className).toMatch(/amber/);
    // Skipped is visually flagged (red tone)
    expect(skippedBadge.className).toMatch(/red/);
  });
});
