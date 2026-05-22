import { describe, expect, test } from "bun:test";
import { createEmptyCostLedger, recordProviderAttemptCost, shouldPauseForBudget } from "../src/costLedger";

describe("cost ledger", () => {
  test("records dispatches even when usage is unknown", () => {
    const ledger = createEmptyCostLedger();
    recordProviderAttemptCost(ledger, {
      task_id: "task_a",
      role: "implement",
      requested_model: { model: "gpt-5.5", reasoning: "high" },
      actual_model: { model: null, reasoning: null, source: "unknown" },
      usage: null,
      usage_source: "unknown"
    });

    expect(ledger.totals.dispatches).toBe(1);
    expect(ledger.by_task.task_a?.model).toBe("gpt-5.5");
    expect(ledger.by_task.task_a?.cost_usd).toBe(0);
  });

  test("pauses only when a configured cap is exceeded", () => {
    const ledger = createEmptyCostLedger();
    ledger.totals.cost_usd = 1.25;

    expect(shouldPauseForBudget(ledger, { budget_cap_usd: 1, budget_action: "pause" })).toBe(true);
    expect(shouldPauseForBudget(ledger, { budget_cap_usd: 1, budget_action: "warn" })).toBe(false);
    expect(shouldPauseForBudget(ledger, { budget_cap_usd: null, budget_action: "pause" })).toBe(false);
  });
});
