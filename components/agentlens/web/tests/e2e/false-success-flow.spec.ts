import { expect, type Page, type Route, test } from "@playwright/test";

const runId = "run_false_success";
const evidenceSha = "sha256:abc123";

const run = {
  run_id: runId,
  workspace_id: "ws_demo",
  parent_run_id: null,
  started_at: "2026-01-01T00:00:00Z",
  ended_at: "2026-01-01T00:00:12Z",
  agent_name: "codex",
  agent_mode: "cli",
  recording_mode: "full",
  agent_outcome: "success",
  eval_status: "failed",
  sealed_phase: "final",
};

const failure = {
  run_id: runId,
  workspace_id: "ws_demo",
  category: "UNACKNOWLEDGED_FAILED_COMMAND",
  severity: "high",
  blame_scope: "agent",
  summary: "The run claimed success after a command exited non-zero.",
  confidence: 0.91,
  recoverability: "rerun",
  evidence: [evidenceSha],
};

const runDetail = {
  ...run,
  agent: "codex",
  workspace_short: "demo",
  summary: "Agent reported success, evaluator found failed command evidence.",
  failures: [failure],
  risks: [],
  manifest_seal: {
    phase: "final",
    manifest_digest: "sha256:manifestdigest",
    integrity: "ok",
    mismatches_count: 0,
  },
};

const events = [
  { type: "command.started", command: "npm test" },
  {
    type: "command.finished",
    command: "npm test",
    exit_code: 1,
    evidence_sha: evidenceSha,
  },
  { type: "run.finalized", agent_outcome: "success" },
];

async function fulfillJson(route: Route, payload: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

async function installApiMocks(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === "/api/v1/meta") {
      await fulfillJson(route, {
        agentlens_version: "0.1.0",
        schema_version: "v1",
        store_path: "/tmp/agentlens",
        store_exists: true,
        demo_mode: true,
      });
      return;
    }

    if (url.pathname === "/api/v1/doctor") {
      await fulfillJson(route, { integrations: {}, paths: {}, warnings: [] });
      return;
    }

    if (url.pathname === "/api/v1/workspaces") {
      await fulfillJson(route, [
        {
          workspace_id: "ws_demo",
          workspace_short: "demo",
          id_basis: "path",
          run_count: 1,
          latest_started_at: run.started_at,
        },
      ]);
      return;
    }

    if (url.pathname === "/api/v1/runs") {
      await fulfillJson(route, { items: [run], next_cursor: null });
      return;
    }

    if (url.pathname === `/api/v1/runs/${runId}/events`) {
      await route.fulfill({
        status: 200,
        contentType: "application/x-ndjson",
        body: `${events.map((event) => JSON.stringify(event)).join("\n")}\n`,
      });
      return;
    }

    if (url.pathname === `/api/v1/runs/${runId}/failures`) {
      await fulfillJson(route, [failure]);
      return;
    }

    if (url.pathname === `/api/v1/runs/${runId}`) {
      await fulfillJson(route, runDetail);
      return;
    }

    await fulfillJson(route, { detail: `Unhandled API mock: ${url.pathname}` }, 404);
  });
}

test("opens false-success evidence from list to transcript", async ({ page }) => {
  await installApiMocks(page);

  await page.goto("/");

  const row = page.locator("tr.false-success-row").filter({ hasText: runId });
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
  await expect(row).toBeVisible();
  await expect(row).toContainText("success");
  await expect(row).toContainText("failed");

  await row.getByRole("link", { name: runId }).click();

  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`));
  await expect(page.getByText("Agent claims")).toBeVisible();
  await expect(page.getByText("Evaluator says")).toBeVisible();
  await expect(page.getByText(/1 failures.*discrepancy/)).toBeVisible();
  await expect(page.getByRole("tab", { name: "Failures (1)" })).toHaveAttribute(
    "data-state",
    "active",
  );
  await expect(page.getByText("UNACKNOWLEDGED_FAILED_COMMAND")).toBeVisible();
  await expect(page.getByText(failure.summary)).toBeVisible();

  await page.getByRole("button", { name: evidenceSha }).click();

  await expect(page.getByRole("tab", { name: "Transcript" })).toHaveAttribute(
    "data-state",
    "active",
  );
  await expect(page.getByText("command.finished")).toBeVisible();
  await expect(
    page.locator(".bg-yellow-50").filter({ hasText: evidenceSha }),
  ).toBeVisible();
});
