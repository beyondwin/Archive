import type { WaygentRunResult, RunWaygentOptions } from "./orchestrator";
import { runWaygent } from "./orchestrator";

export interface PlanChainItem {
  index: number;
  plan: string;
  spec: string | null;
}

export interface PlanChainOptions extends Omit<RunWaygentOptions, "plan" | "plan_path" | "spec" | "run_id"> {
  chain_id: string;
  plans: string[];
  specs?: string[];
}

export interface PlanChainResult {
  schema: "waygent.plan_chain.v1";
  chain_id: string;
  status: "completed" | "blocked" | "failed";
  children: Array<{ index: number; run_id: string; status: string; result?: WaygentRunResult }>;
}

export function validatePlanChainInputs(input: { plans: string[]; specs?: string[] }): PlanChainItem[] {
  if (input.plans.length === 0) throw new Error("plan chain requires at least one --plan");
  const specs = input.specs ?? [];
  if (specs.length > 0 && specs.length !== input.plans.length) {
    throw new Error(`mismatched plan/spec counts: ${input.plans.length} plans, ${specs.length} specs`);
  }
  return input.plans.map((plan, index) => ({
    index: index + 1,
    plan,
    spec: specs[index] ?? null
  }));
}

export async function runPlanChain(options: PlanChainOptions): Promise<PlanChainResult> {
  const items = validatePlanChainInputs({
    plans: options.plans,
    ...(options.specs ? { specs: options.specs } : {})
  });
  const children: PlanChainResult["children"] = [];
  for (const item of items) {
    const runId = `${options.chain_id}_${item.index}`;
    const result = await runWaygent({
      ...options,
      run_id: runId,
      plan_path: item.plan,
      ...(item.spec ? { spec: item.spec } : {})
    });
    const status = result.failures.length > 0 ? "blocked" : "completed";
    children.push({ index: item.index, run_id: runId, status, result });
    if (status !== "completed") {
      return { schema: "waygent.plan_chain.v1", chain_id: options.chain_id, status: "blocked", children };
    }
  }
  return { schema: "waygent.plan_chain.v1", chain_id: options.chain_id, status: "completed", children };
}
