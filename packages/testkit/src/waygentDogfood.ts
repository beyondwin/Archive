import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { AgentLensEvent, OperationalMaturityProjection, WaygentRunStateV2 } from "@waygent/contracts";
import { projectOperationalMaturityFromState } from "@waygent/lens-projectors";

export interface WaygentDogfoodCheckOptions {
  root?: string;
  workspace?: string;
  run_id?: string;
}

export interface WaygentDogfoodCheckResult {
  status: "passed" | "failed";
  run_id: string;
  root: string;
  workspace: string;
  maturity: OperationalMaturityProjection;
  explain: { run_id: string; blocked_by: string | null; summary: string };
  failed_checks: string[];
}

interface OrchestratorDogfoodApi {
  runWaygentDemo(options: { root: string; run_id: string; workspace: string }): Promise<{ events: AgentLensEvent[] }>;
  readRunStateV2(root: string, runId: string): WaygentRunStateV2;
  explainRun(options: { root: string; run: string }): { run_id: string; blocked_by: string | null; summary: string };
}

export async function runWaygentDogfoodCheck(options: WaygentDogfoodCheckOptions = {}): Promise<WaygentDogfoodCheckResult> {
  const root = options.root ?? mkdtempSync(join(tmpdir(), "waygent-dogfood-root-"));
  const workspace = options.workspace ?? initDogfoodSourceCheckout();
  const runId = options.run_id ?? "run_waygent_dogfood";
  const orchestrator = await loadOrchestratorDogfoodApi();
  const result = await orchestrator.runWaygentDemo({ root, run_id: runId, workspace });
  const state = orchestrator.readRunStateV2(root, runId);
  const maturity = projectOperationalMaturityFromState({ state, events: result.events });
  const explain = orchestrator.explainRun({ root, run: runId });
  const failedChecks = dogfoodFailedChecks(maturity, explain);
  return {
    status: failedChecks.length === 0 ? "passed" : "failed",
    run_id: runId,
    root,
    workspace,
    maturity,
    explain,
    failed_checks: failedChecks
  };
}

async function loadOrchestratorDogfoodApi(): Promise<OrchestratorDogfoodApi> {
  const dynamicImport = new Function("specifier", "return import(specifier)") as (
    specifier: string
  ) => Promise<Partial<OrchestratorDogfoodApi>>;
  const module = await dynamicImport("@waygent/orchestrator");
  if (!module.runWaygentDemo || !module.readRunStateV2 || !module.explainRun) {
    throw new Error("@waygent/orchestrator does not export dogfood helpers");
  }
  return module as OrchestratorDogfoodApi;
}

function dogfoodFailedChecks(
  maturity: OperationalMaturityProjection,
  explain: { summary: string }
): string[] {
  const failures: string[] = [];
  if (maturity.projection_errors.length > 0) {
    failures.push(`projection_errors:${maturity.projection_errors.map((error) => error.projection).join(",")}`);
  }
  if (maturity.dogfood_evidence.status !== "complete") {
    failures.push(`dogfood_evidence:${maturity.dogfood_evidence.status}`);
  }
  if (maturity.runtime_cost.measured_wave_count < 1) {
    failures.push("runtime_cost:missing_wave_count");
  }
  if (maturity.provider_readiness.status !== "ready") {
    failures.push(`provider_readiness:${maturity.provider_readiness.status}`);
  }
  if (maturity.dogfood_evidence.checklist.find((item) => item.item === "artifact_index")?.status !== "present") {
    failures.push("artifact_index:missing");
  }
  if (maturity.dogfood_evidence.checklist.find((item) => item.item === "task_phase_timings")?.status !== "present") {
    failures.push("task_phase_timings:missing");
  }
  if (maturity.dogfood_evidence.checklist.find((item) => item.item === "provider_attempts")?.status !== "present") {
    failures.push("provider_attempts:missing");
  }
  if (maturity.dogfood_evidence.checklist.find((item) => item.item === "verification_records")?.status !== "present") {
    failures.push("verification_records:missing");
  }
  if (!maturity.dogfood_evidence.real_runtime_timestamps) {
    failures.push("runtime_timestamps:fixed_or_missing");
  }
  if (/\bunknown\b/i.test(explain.summary)) {
    failures.push("explain:unknown");
  }
  return failures;
}

function initDogfoodSourceCheckout(): string {
  const workspace = mkdtempSync(join(tmpdir(), "waygent-dogfood-source-"));
  writeFileSync(join(workspace, "README.md"), "dogfood fixture\n");
  for (const args of [
    ["init", "-q"],
    ["config", "user.email", "test@example.com"],
    ["config", "user.name", "Waygent"],
    ["add", "-A"],
    ["commit", "-q", "-m", "init"]
  ]) {
    const result = Bun.spawnSync(["git", ...args], { cwd: workspace });
    if (result.exitCode !== 0) throw new Error(`git ${args.join(" ")} failed`);
  }
  return workspace;
}
