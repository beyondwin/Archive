import { describe, expect, test } from "bun:test";
import type { ProviderAttempt } from "@waygent/contracts";
import {
  budgetPolicyStateRecord,
  evaluateBudgetPolicy,
  markBudgetWarningEmitted,
  projectBudgetPolicy,
  resolveBudgetPolicy
} from "../src/budgetPolicy";
import { createEmptyCostLedger } from "../src/costLedger";

describe("budget policy", () => {
  test("defaults to no hard cost cap with standard warning thresholds and retry caps", () => {
    const policy = resolveBudgetPolicy();

    expect(policy).toMatchObject({
      max_cost_usd: null,
      max_provider_minutes: null,
      max_full_worker_retries_per_task: 1,
      max_repair_retries_per_task: 2,
      max_adapter_crash_retries_per_task: 1,
      warning_thresholds_usd: [50, 100, 250, 500],
      action: "off"
    });
  });

  test("emits warning decisions once per crossed cost threshold", () => {
    const ledger = createEmptyCostLedger();
    ledger.totals.cost_usd = 125;
    const policy = resolveBudgetPolicy();

    const first = evaluateBudgetPolicy(policy, ledger);
    expect(first).toMatchObject({
      action: "warn",
      reason: "cost_warning_threshold_exceeded",
      warning_threshold_usd: 50,
      projection: { budget_status: "warning", next_warning_threshold_usd: 250 }
    });

    const second = evaluateBudgetPolicy(markBudgetWarningEmitted(policy, 50), ledger);
    expect(second.warning_threshold_usd).toBe(100);
  });

  test("projects remaining budget and pauses when a hard cost cap is exceeded", () => {
    const ledger = createEmptyCostLedger();
    ledger.totals.cost_usd = 51;
    const policy = resolveBudgetPolicy({ max_cost_usd: 50, action: "pause_for_operator" });

    expect(evaluateBudgetPolicy(policy, ledger)).toMatchObject({
      action: "pause_for_operator",
      reason: "max_cost_usd_exceeded",
      projection: {
        budget_status: "paused",
        remaining_cost_usd: -1,
        exceeded: ["max_cost_usd"]
      }
    });
  });

  test("projects provider runtime minutes as budget evidence", () => {
    const attempts: ProviderAttempt[] = [{
      schema: "runway.provider_attempt.v1",
      attempt_id: "attempt_a",
      run_id: "run_a",
      task_id: "task_a",
      role: "implement",
      provider: "fake",
      command: ["fake-provider"],
      cwd: "/tmp/work",
      stdin_ref: "provider/in.txt",
      stdout_ref: "provider/out.txt",
      stderr_ref: "provider/err.txt",
      event_stream_ref: null,
      exit_code: 0,
      timed_out: false,
      started_at: "2026-05-22T00:00:00.000Z",
      completed_at: "2026-05-22T00:02:30.000Z",
      worker_result_ref: "worker/result.json",
      failure_class: null,
      actual_model: { model: "fake", reasoning: null, source: "provider" },
      usage: null,
      usage_source: "unknown"
    }];
    const projection = projectBudgetPolicy(resolveBudgetPolicy({ max_provider_minutes: 2, action: "pause_for_operator" }), undefined, attempts);

    expect(projection).toMatchObject({
      provider_minutes: 2.5,
      budget_status: "paused",
      remaining_provider_minutes: -0.5,
      reason: "max_provider_minutes_exceeded"
    });
  });

  test("serializes policy for run state without losing retry settings", () => {
    const policy = resolveBudgetPolicy({
      budget_cap_usd: 25,
      budget_action: "pause",
      max_repair_retries_per_task: 1,
      max_full_worker_retries_per_task: 0
    });

    expect(budgetPolicyStateRecord(policy)).toMatchObject({
      max_cost_usd: 25,
      max_repair_retries_per_task: 1,
      max_full_worker_retries_per_task: 0,
      action: "pause_for_operator"
    });
  });
});
