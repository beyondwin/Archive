import type { CostLedger, ProviderAttempt, WaygentRunStateV2 } from "@waygent/contracts";

export type BudgetPolicyAction = "pause_for_operator" | "warn" | "off";

export interface RunBudgetPolicy {
  max_cost_usd: number | null;
  max_provider_minutes: number | null;
  max_full_worker_retries_per_task: number;
  max_repair_retries_per_task: number;
  max_adapter_crash_retries_per_task: number;
  warning_thresholds_usd: number[];
  action: BudgetPolicyAction;
  emitted_warning_thresholds_usd: number[];
}

export interface BudgetPolicyInput {
  max_cost_usd?: number | null;
  max_provider_minutes?: number | null;
  max_full_worker_retries_per_task?: number | null;
  max_repair_retries_per_task?: number | null;
  max_adapter_crash_retries_per_task?: number | null;
  warning_thresholds_usd?: number[] | null;
  action?: BudgetPolicyAction | "pause" | null;
  emitted_warning_thresholds_usd?: number[] | null;
  budget_cap_usd?: number | null;
  budget_action?: "warn" | "pause" | "off" | "pause_for_operator" | null;
}

export interface BudgetProjection {
  cost_usd: number;
  provider_minutes: number;
  dispatches: number;
  budget_status: "ok" | "warning" | "paused" | "exhausted";
  max_cost_usd: number | null;
  max_provider_minutes: number | null;
  remaining_cost_usd: number | null;
  remaining_provider_minutes: number | null;
  next_warning_threshold_usd: number | null;
  exceeded: Array<"max_cost_usd" | "max_provider_minutes">;
  reason: string;
}

export interface BudgetEvaluation {
  action: "continue" | "warn" | "pause_for_operator";
  reason: string;
  warning_threshold_usd: number | null;
  projection: BudgetProjection;
}

export const DEFAULT_BUDGET_WARNING_THRESHOLDS_USD = [50, 100, 250, 500] as const;

export function resolveBudgetPolicy(input: BudgetPolicyInput = {}): RunBudgetPolicy {
  const maxCost = firstNumberOrNull(input.max_cost_usd, input.budget_cap_usd);
  const action = normalizeAction(input.action ?? input.budget_action ?? "off");
  return {
    max_cost_usd: maxCost,
    max_provider_minutes: numberOrNull(input.max_provider_minutes),
    max_full_worker_retries_per_task: positiveInteger(input.max_full_worker_retries_per_task, 1),
    max_repair_retries_per_task: positiveInteger(input.max_repair_retries_per_task, 2),
    max_adapter_crash_retries_per_task: positiveInteger(input.max_adapter_crash_retries_per_task, 1),
    warning_thresholds_usd: normalizeThresholds(input.warning_thresholds_usd),
    action,
    emitted_warning_thresholds_usd: normalizeEmittedThresholds(input.emitted_warning_thresholds_usd)
  };
}

export function budgetPolicyStateRecord(policy: RunBudgetPolicy): Record<string, unknown> {
  return {
    max_cost_usd: policy.max_cost_usd,
    max_provider_minutes: policy.max_provider_minutes,
    max_full_worker_retries_per_task: policy.max_full_worker_retries_per_task,
    max_repair_retries_per_task: policy.max_repair_retries_per_task,
    max_adapter_crash_retries_per_task: policy.max_adapter_crash_retries_per_task,
    warning_thresholds_usd: [...policy.warning_thresholds_usd],
    emitted_warning_thresholds_usd: [...policy.emitted_warning_thresholds_usd],
    action: policy.action
  };
}

export function budgetPolicyFromRunState(state: WaygentRunStateV2): RunBudgetPolicy {
  const stored = recordOf(state.budget_policy);
  const input: BudgetPolicyInput = {
    max_cost_usd: numericField(stored, "max_cost_usd"),
    max_provider_minutes: numericField(stored, "max_provider_minutes"),
    max_full_worker_retries_per_task: numericField(stored, "max_full_worker_retries_per_task"),
    max_repair_retries_per_task: numericField(stored, "max_repair_retries_per_task"),
    max_adapter_crash_retries_per_task: numericField(stored, "max_adapter_crash_retries_per_task"),
    warning_thresholds_usd: numericArrayField(stored, "warning_thresholds_usd"),
    emitted_warning_thresholds_usd: numericArrayField(stored, "emitted_warning_thresholds_usd"),
    action: actionField(stored, "action")
  };
  if (state.budget_cap_usd !== undefined) input.budget_cap_usd = state.budget_cap_usd;
  if (state.budget_action !== undefined) input.budget_action = state.budget_action;
  return resolveBudgetPolicy(input);
}

export function evaluateBudgetPolicy(
  policy: RunBudgetPolicy,
  ledger: CostLedger | undefined,
  providerAttempts: ProviderAttempt[] = []
): BudgetEvaluation {
  const projection = projectBudgetPolicy(policy, ledger, providerAttempts);
  if (projection.budget_status === "paused") {
    return { action: "pause_for_operator", reason: projection.reason, warning_threshold_usd: null, projection };
  }
  const warningThreshold = nextUnemittedWarningThreshold(policy, projection.cost_usd);
  if (warningThreshold !== null) {
    return {
      action: "warn",
      reason: "cost_warning_threshold_exceeded",
      warning_threshold_usd: warningThreshold,
      projection: { ...projection, budget_status: projection.budget_status === "ok" ? "warning" : projection.budget_status, reason: "cost_warning_threshold_exceeded" }
    };
  }
  return { action: "continue", reason: projection.reason, warning_threshold_usd: null, projection };
}

export function projectBudgetPolicy(
  policy: RunBudgetPolicy,
  ledger: CostLedger | undefined,
  providerAttempts: ProviderAttempt[] = []
): BudgetProjection {
  const costUsd = round(ledger?.totals.cost_usd ?? 0);
  const providerMinutes = round(providerRuntimeMinutes(providerAttempts));
  const dispatches = ledger?.totals.dispatches ?? providerAttempts.length;
  const exceeded: BudgetProjection["exceeded"] = [];
  if (typeof policy.max_cost_usd === "number" && costUsd > policy.max_cost_usd) exceeded.push("max_cost_usd");
  if (typeof policy.max_provider_minutes === "number" && providerMinutes > policy.max_provider_minutes) exceeded.push("max_provider_minutes");
  const warningThreshold = currentWarningThreshold(policy.warning_thresholds_usd, costUsd);
  const hardCapExceeded = exceeded.length > 0;
  const budgetStatus: BudgetProjection["budget_status"] = hardCapExceeded
    ? policy.action === "pause_for_operator" ? "paused" : "exhausted"
    : warningThreshold !== null ? "warning" : "ok";
  return {
    cost_usd: costUsd,
    provider_minutes: providerMinutes,
    dispatches,
    budget_status: budgetStatus,
    max_cost_usd: policy.max_cost_usd,
    max_provider_minutes: policy.max_provider_minutes,
    remaining_cost_usd: typeof policy.max_cost_usd === "number" ? round(policy.max_cost_usd - costUsd) : null,
    remaining_provider_minutes: typeof policy.max_provider_minutes === "number" ? round(policy.max_provider_minutes - providerMinutes) : null,
    next_warning_threshold_usd: nextWarningThreshold(policy.warning_thresholds_usd, costUsd),
    exceeded,
    reason: hardCapExceeded
      ? exceeded.includes("max_cost_usd") ? "max_cost_usd_exceeded" : "max_provider_minutes_exceeded"
      : warningThreshold !== null ? "cost_warning_threshold_exceeded" : "budget_within_policy"
  };
}

export function markBudgetWarningEmitted(policy: RunBudgetPolicy, threshold: number): RunBudgetPolicy {
  return {
    ...policy,
    emitted_warning_thresholds_usd: normalizeThresholds([...policy.emitted_warning_thresholds_usd, threshold])
  };
}

function providerRuntimeMinutes(attempts: ProviderAttempt[]): number {
  return attempts.reduce((total, attempt) => {
    const started = Date.parse(attempt.started_at);
    const completed = attempt.completed_at ? Date.parse(attempt.completed_at) : Number.NaN;
    if (!Number.isFinite(started) || !Number.isFinite(completed) || completed <= started) return total;
    return total + (completed - started) / 60_000;
  }, 0);
}

function nextUnemittedWarningThreshold(policy: RunBudgetPolicy, costUsd: number): number | null {
  return policy.warning_thresholds_usd.find((threshold) =>
    costUsd >= threshold && !policy.emitted_warning_thresholds_usd.includes(threshold)
  ) ?? null;
}

function currentWarningThreshold(thresholds: number[], costUsd: number): number | null {
  const hit = thresholds.filter((threshold) => costUsd >= threshold).at(-1);
  return typeof hit === "number" ? hit : null;
}

function nextWarningThreshold(thresholds: number[], costUsd: number): number | null {
  return thresholds.find((threshold) => costUsd < threshold) ?? null;
}

function normalizeAction(value: BudgetPolicyInput["action"] | BudgetPolicyInput["budget_action"]): BudgetPolicyAction {
  if (value === "pause" || value === "pause_for_operator") return "pause_for_operator";
  if (value === "warn") return "warn";
  return "off";
}

function firstNumberOrNull(...values: Array<unknown>): number | null {
  for (const value of values) {
    const numeric = numberOrNull(value);
    if (numeric !== null) return numeric;
  }
  return null;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function positiveInteger(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : fallback;
}

function normalizeThresholds(value: unknown): number[] {
  const source = Array.isArray(value) ? value : [...DEFAULT_BUDGET_WARNING_THRESHOLDS_USD];
  return [...new Set(source.filter((item): item is number => typeof item === "number" && Number.isFinite(item) && item > 0))]
    .sort((a, b) => a - b);
}

function normalizeEmittedThresholds(value: unknown): number[] {
  const source = Array.isArray(value) ? value : [];
  return [...new Set(source.filter((item): item is number => typeof item === "number" && Number.isFinite(item) && item > 0))]
    .sort((a, b) => a - b);
}

function recordOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function numericField(record: Record<string, unknown>, key: string): number | null {
  return numberOrNull(record[key]);
}

function numericArrayField(record: Record<string, unknown>, key: string): number[] | null {
  return Array.isArray(record[key]) ? record[key].filter((item): item is number => typeof item === "number") : null;
}

function actionField(record: Record<string, unknown>, key: string): BudgetPolicyAction | "pause" | null {
  const value = record[key];
  return value === "pause_for_operator" || value === "pause" || value === "warn" || value === "off" ? value : null;
}

function round(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
}
