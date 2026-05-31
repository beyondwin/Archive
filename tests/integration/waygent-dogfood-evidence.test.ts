import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { createApiHandler } from "../../apps/api/src/server";
import { buildRunDetailModel, type RealRunDetailResponse } from "../../apps/console/src/uiModel";
import { runWaygentDogfoodCheck } from "../../packages/testkit/src";

describe("Waygent dogfood evidence gate", () => {
  test("offline fake-provider dogfood run has complete maturity evidence", async () => {
    const check = await runWaygentDogfoodCheck({
      root: mkdtempSync(join(tmpdir(), "waygent-dogfood-root-"))
    });

    expect(check.status).toBe("passed");
    expect(check.failed_checks).toEqual([]);
    expect(check.maturity.dogfood_evidence.status).toBe("complete");
    expect(check.maturity.runtime_cost.measured_wave_count).toBeGreaterThanOrEqual(1);
    expect(check.maturity.provider_readiness.status).toBe("ready");
    expect(check.explain.summary).not.toContain("unknown");
  });

  test("explain, API, and console detail agree on operator blocker and action", async () => {
    const check = await runWaygentDogfoodCheck({
      root: mkdtempSync(join(tmpdir(), "waygent-dogfood-agreement-root-")),
      run_id: "run_waygent_dogfood_agreement"
    });
    const handler = createApiHandler({ runRoot: check.root });
    const response = await handler(new Request(`http://127.0.0.1/runs/${check.run_id}`));
    const detail = await response.json() as RealRunDetailResponse;
    const consoleDetail = buildRunDetailModel(detail);

    const explainDecision = check.explain.operator_decision;
    const apiDecision = detail.operator_decision;
    const consoleDecision = consoleDetail.operator_decision;

    expect(apiDecision).toBeTruthy();
    expect(consoleDecision).toBeTruthy();
    expect(check.explain.blocked_by).toBe(apiDecision?.primary_blocker?.code ?? null);
    expect(consoleDetail.outcome_strip.primary_blocker).toBe(apiDecision?.primary_blocker?.code ?? null);
    expect(primaryOperatorAction(explainDecision)).toBe(primaryOperatorAction(apiDecision));
    expect(primaryOperatorAction(consoleDecision)).toBe(primaryOperatorAction(apiDecision));
  });
});

function primaryOperatorAction(decision: RealRunDetailResponse["operator_decision"]): string | null {
  const action = decision?.allowed_actions.find((candidate) =>
    !["inspect_run", "explain_run", "open_raw_evidence"].includes(candidate.id)
  ) ?? decision?.allowed_actions[0];
  return action?.id ?? null;
}
