import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";

import { EmptyRoute } from "@/routes/empty";
import { RunDetailRoute } from "@/routes/run-detail";
import { RunsListRoute } from "@/routes/runs-list";
import {
  agentLensApiHandlers,
  defaultMeta,
  falseSuccessArtifacts,
  falseSuccessRun,
} from "@/test-mocks/agentlens-api";
import { server } from "@/test-mocks/server";

import { renderWithProviders } from "./render";

function renderRunsRoutes() {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<RunsListRoute />} />
      <Route path="/empty" element={<EmptyRoute />} />
    </Routes>,
  );
}

function renderRunDetailRoute(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/runs/:runId" element={<RunDetailRoute />} />
    </Routes>,
    { route },
  );
}

describe("RunsListRoute", () => {
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => server.resetHandlers());
  afterAll(() => server.close());

  it("highlights false-success rows returned by the API", async () => {
    server.use(
      ...agentLensApiHandlers({
        meta: { ...defaultMeta, store_exists: true },
        runs: [falseSuccessRun],
      }),
    );

    renderRunsRoutes();

    const runLink = await screen.findByRole("link", {
      name: falseSuccessRun.run_id,
    });
    expect(screen.getByText("1 visible · newest first")).toBeInTheDocument();
    expect(runLink.closest("tr")).toHaveClass("false-success-row");
    expect(within(runLink.closest("tr") as HTMLElement).getByText("failed")).toBeInTheDocument();
  });

  it("routes to the empty-state page when the store does not exist", async () => {
    server.use(
      ...agentLensApiHandlers({
        meta: { ...defaultMeta, store_exists: false },
        runs: [],
      }),
    );

    renderRunsRoutes();

    expect(
      await screen.findByRole("heading", { name: "No runs found" }),
    ).toBeInTheDocument();
    expect(screen.getByText("agentlens run -- <command>")).toBeInTheDocument();
  });

  it("routes to the empty-state page when an existing store has zero runs", async () => {
    server.use(
      ...agentLensApiHandlers({
        meta: { ...defaultMeta, store_exists: true },
        runs: [],
      }),
    );

    renderRunsRoutes();

    expect(
      await screen.findByRole("heading", { name: "No runs found" }),
    ).toBeInTheDocument();
    expect(screen.getByText("agentlens eval --latest")).toBeInTheDocument();
  });

  it("applies agent, eval status, and since filters to the runs query", async () => {
    const recentCodexRun = {
      ...falseSuccessRun,
      run_id: "run_recent_codex_failed",
      started_at: new Date().toISOString(),
      failures_count: 2,
    };
    const oldCodexRun = {
      ...falseSuccessRun,
      run_id: "run_old_codex_failed",
      started_at: "2024-01-01T00:00:00Z",
      failures_count: 1,
    };
    const recentClaudeRun = {
      ...falseSuccessRun,
      run_id: "run_recent_claude_passed",
      agent_name: "claude",
      agent_outcome: "success",
      eval_status: "passed",
      started_at: new Date().toISOString(),
      failures_count: 0,
    };
    const user = userEvent.setup();

    server.use(
      ...agentLensApiHandlers({
        meta: { ...defaultMeta, store_exists: true },
        runs: [recentCodexRun, oldCodexRun, recentClaudeRun],
      }),
    );

    renderRunsRoutes();

    expect(await screen.findByRole("link", { name: recentCodexRun.run_id })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: oldCodexRun.run_id })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: recentClaudeRun.run_id })).toBeInTheDocument();

    await user.click(screen.getByRole("textbox", { name: "Agent" }));
    await user.paste("codex");
    await user.selectOptions(screen.getByRole("combobox", { name: "Eval status" }), "failed");
    await user.selectOptions(screen.getByRole("combobox", { name: "Since" }), "30");

    expect(
      await screen.findByRole("link", { name: recentCodexRun.run_id }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: oldCodexRun.run_id })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: recentClaudeRun.run_id }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("1 visible · newest first")).toBeInTheDocument();
  });

  it("applies typed agent and agent outcome filters without requiring loaded agent options", async () => {
    const codexFailedRun = {
      ...falseSuccessRun,
      run_id: "run_codex_failed",
      agent_name: "codex",
      agent_outcome: "failed",
      eval_status: "failed",
      failures_count: 1,
    };
    const rareSuccessRun = {
      ...falseSuccessRun,
      run_id: "run_rare_agent_success",
      agent_name: "rare-agent",
      agent_outcome: "success",
      eval_status: "passed",
      failures_count: 0,
    };
    const user = userEvent.setup();

    server.use(
      ...agentLensApiHandlers({
        meta: { ...defaultMeta, store_exists: true },
        runs: [codexFailedRun, rareSuccessRun],
      }),
    );

    renderRunsRoutes();

    expect(await screen.findByRole("link", { name: codexFailedRun.run_id })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: rareSuccessRun.run_id })).toBeInTheDocument();

    await user.click(screen.getByRole("textbox", { name: "Agent" }));
    await user.paste("rare-agent");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Agent outcome" }),
      "success",
    );

    expect(
      await screen.findByRole("link", { name: rareSuccessRun.run_id }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: codexFailedRun.run_id })).not.toBeInTheDocument();
    expect(screen.getByText("1 visible · newest first")).toBeInTheDocument();
  });

  it("shows manifest seal data and artifact links on run detail", async () => {
    const user = userEvent.setup();
    server.use(
      ...agentLensApiHandlers({
        meta: { ...defaultMeta, store_exists: true },
        artifacts: falseSuccessArtifacts,
      }),
    );

    renderRunDetailRoute(`/runs/${falseSuccessRun.run_id}`);

    const artifactsTab = await screen.findByRole("tab", {
      name: "Artifacts/Seal",
    });
    await user.click(artifactsTab);

    expect(screen.getByText("sha256:manifestdigest")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("0 mismatches")).toBeInTheDocument();
    expect(
      await screen.findByRole("link", { name: "artifacts/report.json" }),
    ).toHaveAttribute(
      "href",
      `/api/v1/runs/${falseSuccessRun.run_id}/artifacts/sha256%3Areport`,
    );
  });
});
