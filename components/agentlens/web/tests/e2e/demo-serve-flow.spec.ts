import { expect, test } from "@playwright/test";

const demoFalseSuccessRunId = "run_20260101_000001_bbbbbb";

test("demo serve exposes the false-success flow through real API routes", async ({ page }) => {
  await page.goto("/");

  const row = page.locator("tr.false-success-row").filter({
    hasText: demoFalseSuccessRunId,
  });
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
  await expect(row).toBeVisible();
  await expect(row).toContainText("success");
  await expect(row).toContainText("failed");
  await expect(row).toContainText("1");

  await row.getByRole("link", { name: demoFalseSuccessRunId }).click();

  await expect(page).toHaveURL(new RegExp(`/runs/${demoFalseSuccessRunId}$`));
  await expect(page.getByText("Agent claims")).toBeVisible();
  await expect(page.getByText("Evaluator says")).toBeVisible();
  await expect(page.getByText("UNACKNOWLEDGED_FAILED_COMMAND")).toBeVisible();
  await expect(
    page.getByText("success outcome but failed commands not acknowledged"),
  ).toBeVisible();

  await page.getByRole("tab", { name: "Artifacts/Seal" }).click();

  await expect(page.getByText("Manifest digest")).toBeVisible();
  await expect(page.getByText("Integrity", { exact: true })).toBeVisible();
  await expect(page.getByText("0 mismatches")).toBeVisible();
  await expect(page.getByText("run.json")).toBeVisible();
});
