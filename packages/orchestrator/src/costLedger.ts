import type { CostLedger, ModelAttestation, ModelRequest, ProviderRole, TokenUsage, UsageSource } from "@waygent/contracts";

export interface CostRecordInput {
  task_id: string;
  role: ProviderRole;
  requested_model?: ModelRequest;
  actual_model?: ModelAttestation;
  usage?: TokenUsage | null;
  usage_source?: UsageSource;
  recorded_at?: string;
}

export interface BudgetPolicy {
  budget_cap_usd?: number | null;
  budget_action?: "warn" | "pause" | "off";
}

const ZERO_USAGE: TokenUsage = {
  input_tokens: 0,
  output_tokens: 0,
  cached_read_tokens: 0,
  cached_write_tokens: 0
};

const PRICE_TABLE_USD_PER_MILLION: Record<string, { input: number; output: number; cached_read?: number; cached_write?: number }> = {
  fake: { input: 0, output: 0, cached_read: 0, cached_write: 0 },
  "gpt-5.5": { input: 1.25, output: 10 },
  "gpt-5.4": { input: 1.25, output: 10 },
  "gpt-5.3-codex": { input: 1.25, output: 10 },
  opus: { input: 15, output: 75 },
  sonnet: { input: 3, output: 15 },
  haiku: { input: 0.8, output: 4 }
};

export function createEmptyCostLedger(): CostLedger {
  return {
    by_task: {},
    by_role: {},
    by_model: {},
    totals: { ...ZERO_USAGE, cost_usd: 0, dispatches: 0 },
    price_table_commit: "2026-05-22.static"
  };
}

export function recordProviderAttemptCost(ledger: CostLedger, input: CostRecordInput): CostLedger {
  const usage = input.usage ?? ZERO_USAGE;
  const model = modelKey(input.actual_model, input.requested_model);
  const cost = input.usage ? estimateCost(model, usage) : 0;
  const recordedAt = input.recorded_at ?? new Date().toISOString();
  const taskBucket = ledger.by_task[input.task_id] ?? {
    usage: { ...ZERO_USAGE },
    cost_usd: 0,
    dispatches: 0,
    last_at: recordedAt,
    model
  };
  addUsage(taskBucket.usage, usage);
  taskBucket.cost_usd += cost;
  taskBucket.dispatches += 1;
  taskBucket.last_at = recordedAt;
  taskBucket.model = model;
  ledger.by_task[input.task_id] = taskBucket;

  const roleBucket = ledger.by_role[input.role] ?? { usage: { ...ZERO_USAGE }, cost_usd: 0, dispatches: 0 };
  addUsage(roleBucket.usage, usage);
  roleBucket.cost_usd += cost;
  roleBucket.dispatches += 1;
  ledger.by_role[input.role] = roleBucket;

  const modelBucket = ledger.by_model[model ?? "unknown"] ?? { usage: { ...ZERO_USAGE }, cost_usd: 0, dispatches: 0 };
  addUsage(modelBucket.usage, usage);
  modelBucket.cost_usd += cost;
  modelBucket.dispatches += 1;
  ledger.by_model[model ?? "unknown"] = modelBucket;

  addUsage(ledger.totals, usage);
  ledger.totals.cost_usd += cost;
  ledger.totals.dispatches += 1;
  return ledger;
}

export function shouldPauseForBudget(ledger: CostLedger | undefined, policy: BudgetPolicy): boolean {
  if (!ledger || policy.budget_action !== "pause") return false;
  if (typeof policy.budget_cap_usd !== "number") return false;
  return ledger.totals.cost_usd > policy.budget_cap_usd;
}

export function shouldWarnForBudget(ledger: CostLedger | undefined, policy: BudgetPolicy): boolean {
  if (!ledger || policy.budget_action !== "warn") return false;
  if (typeof policy.budget_cap_usd !== "number") return false;
  return ledger.totals.cost_usd > policy.budget_cap_usd;
}

function addUsage(target: TokenUsage, usage: TokenUsage): void {
  target.input_tokens += usage.input_tokens;
  target.output_tokens += usage.output_tokens;
  target.cached_read_tokens += usage.cached_read_tokens;
  target.cached_write_tokens += usage.cached_write_tokens;
}

function modelKey(actual: ModelAttestation | undefined, requested: ModelRequest | undefined): string | null {
  if (actual?.model) return actual.model;
  return requested?.model ?? null;
}

function estimateCost(model: string | null, usage: TokenUsage): number {
  if (!model) return 0;
  const normalized = model.toLowerCase();
  const price = PRICE_TABLE_USD_PER_MILLION[normalized] ??
    Object.entries(PRICE_TABLE_USD_PER_MILLION).find(([key]) => normalized.includes(key))?.[1];
  if (!price) return 0;
  return roundUsd(
    usage.input_tokens / 1_000_000 * price.input +
    usage.output_tokens / 1_000_000 * price.output +
    usage.cached_read_tokens / 1_000_000 * (price.cached_read ?? price.input) +
    usage.cached_write_tokens / 1_000_000 * (price.cached_write ?? price.input)
  );
}

function roundUsd(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
}
