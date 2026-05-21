import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";

export type WaygentScenarioProviderFixture = "fake-success" | "malformed-provider" | "live-provider";
export type WaygentScenarioRunStatus = "trusted" | "failed";
export type WaygentScenarioApplyStatus = "not_applied" | "blocked";

export interface WaygentScenarioExpectedReplay {
  run_status: WaygentScenarioRunStatus;
  apply_status: WaygentScenarioApplyStatus;
  event_types: string[];
  total_events?: number;
  safe_wave?: string[];
  checkpoints?: string[];
  blockers?: string[];
}

export interface WaygentScenario {
  id: string;
  title: string;
  provider_fixture: WaygentScenarioProviderFixture;
  source_dirty_before_apply: boolean;
  force_missing_checkpoint: boolean;
  plan: string;
  expected: WaygentScenarioExpectedReplay;
}

export interface NormalizedWaygentReplay {
  run_status: WaygentScenarioRunStatus;
  apply_status: WaygentScenarioApplyStatus;
  total_events: number;
  safe_wave: string[];
  event_types: string[];
  checkpoints: string[];
  blockers?: string[];
  error?: string;
}

export interface WaygentScenarioRunOptions {
  root?: string;
  workspace?: string;
  run_id?: string;
  live_provider?: "codex" | "claude";
  provider_processes?: Partial<Record<"codex" | "claude", ProviderProcessOptionsLike>>;
}

export interface WaygentScenarioRun {
  scenario: WaygentScenario;
  normalized: NormalizedWaygentReplay;
}

interface ReplayLike {
  events?: Array<{
    event_type?: string;
    payload?: Record<string, unknown>;
  }>;
  trust_report?: {
    trust_status?: string;
  };
  summary?: {
    total_events?: number;
  };
  projection?: {
    safe_wave?: string[];
  };
  apply_state?: string;
}

interface ProviderProcessOptionsLike {
  executable?: string;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
  timeout_ms?: number;
}

interface RunWaygentOptionsLike {
  root: string;
  run_id?: string;
  profile?: {
    provider: "fake" | "codex" | "claude";
    execution_mode?: "single-agent" | "multi-agent";
  };
  plan?: string;
  workspace?: string;
  provider_processes?: Partial<Record<"codex" | "claude", ProviderProcessOptionsLike>>;
}

type RunWaygentLike = (options: RunWaygentOptionsLike) => Promise<ReplayLike>;

export function loadWaygentScenario(path: string): WaygentScenario {
  const raw = JSON.parse(readFileSync(path, "utf8")) as Partial<WaygentScenario>;
  if (!raw.id || typeof raw.id !== "string") throw new Error(`${basename(path)} is missing id`);
  if (!raw.title || typeof raw.title !== "string") throw new Error(`${raw.id} is missing title`);
  if (!isProviderFixture(raw.provider_fixture)) throw new Error(`${raw.id} has invalid provider_fixture`);
  if (typeof raw.source_dirty_before_apply !== "boolean") {
    throw new Error(`${raw.id} must set source_dirty_before_apply`);
  }
  if (typeof raw.force_missing_checkpoint !== "boolean") {
    throw new Error(`${raw.id} must set force_missing_checkpoint`);
  }
  if (!raw.plan || typeof raw.plan !== "string") throw new Error(`${raw.id} is missing plan`);
  if (!raw.expected) throw new Error(`${raw.id} is missing expected replay`);
  return raw as WaygentScenario;
}

export function normalizeWaygentReplay(
  replay: ReplayLike,
  options: {
    apply_status?: WaygentScenarioApplyStatus;
    force_missing_checkpoint?: boolean;
    blockers?: string[];
    error?: string;
  } = {}
): NormalizedWaygentReplay {
  const events = replay.events ?? [];
  const runStatus = replay.trust_report?.trust_status === "trusted" && !hasFailedWorker(events) ? "trusted" : "failed";
  const checkpoints = options.force_missing_checkpoint ? [] : uniqueStrings(events.flatMap((event) => checkpointRefs(event.payload)));
  const normalized: NormalizedWaygentReplay = {
    run_status: runStatus,
    apply_status: options.apply_status ?? normalizeApplyStatus(replay.apply_state),
    total_events: replay.summary?.total_events ?? events.length,
    safe_wave: replay.projection?.safe_wave ?? [],
    event_types: events.map((event) => String(event.event_type)),
    checkpoints
  };
  if (options.blockers && options.blockers.length > 0) normalized.blockers = options.blockers;
  if (options.error) normalized.error = options.error;
  return normalized;
}

export async function runWaygentScenario(
  scenario: WaygentScenario,
  options: WaygentScenarioRunOptions = {}
): Promise<WaygentScenarioRun> {
  const blockers = scenarioBlockers(scenario);
  const root = options.root ?? mkdtempSync(join(tmpdir(), "waygent-scenario-run-"));
  try {
    const runWaygent = await loadRunWaygent();
    const runOptions: RunWaygentOptionsLike = {
      root,
      run_id: options.run_id ?? `scenario_${scenario.id}`,
      plan: scenario.plan,
      ...providerOptions(scenario, options)
    };
    if (options.workspace) runOptions.workspace = options.workspace;
    const result = await runWaygent(runOptions);
    return {
      scenario,
      normalized: normalizeWaygentReplay(result, {
        apply_status: blockers.length > 0 ? "blocked" : "not_applied",
        force_missing_checkpoint: scenario.force_missing_checkpoint,
        blockers
      })
    };
  } catch (error) {
    return {
      scenario,
      normalized: {
        run_status: "failed",
        apply_status: blockers.length > 0 ? "blocked" : "not_applied",
        total_events: 0,
        safe_wave: [],
        event_types: [],
        checkpoints: [],
        ...(blockers.length > 0 ? { blockers } : {}),
        error: error instanceof Error ? error.message : String(error)
      }
    };
  }
}

function isProviderFixture(value: unknown): value is WaygentScenarioProviderFixture {
  return value === "fake-success" || value === "malformed-provider" || value === "live-provider";
}

function normalizeApplyStatus(value: unknown): WaygentScenarioApplyStatus {
  return value === "blocked" ? "blocked" : "not_applied";
}

function providerOptions(
  scenario: WaygentScenario,
  options: WaygentScenarioRunOptions
): Pick<RunWaygentOptionsLike, "profile" | "provider_processes"> {
  if (scenario.provider_fixture === "live-provider") {
    const provider = options.live_provider;
    if (!provider) throw new Error("live-provider scenario requires WAYGENT_LIVE_PROVIDER=codex or claude");
    const resolved: Pick<RunWaygentOptionsLike, "profile" | "provider_processes"> = {
      profile: { provider, execution_mode: "multi-agent" }
    };
    if (options.provider_processes) resolved.provider_processes = options.provider_processes;
    return resolved;
  }
  if (scenario.provider_fixture === "malformed-provider") {
    return {
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: {
        ...options.provider_processes,
        codex: {
          executable: process.execPath,
          args: ["-e", "process.stdout.write('{not json')"]
        }
      }
    };
  }
  return { profile: { provider: "fake", execution_mode: "multi-agent" } };
}

async function loadRunWaygent(): Promise<RunWaygentLike> {
  const dynamicImport = new Function("specifier", "return import(specifier)") as (
    specifier: string
  ) => Promise<{ runWaygent?: RunWaygentLike }>;
  const module = await dynamicImport("@waygent/orchestrator");
  if (!module.runWaygent) throw new Error("@waygent/orchestrator does not export runWaygent");
  return module.runWaygent;
}

function scenarioBlockers(scenario: WaygentScenario): string[] {
  const blockers: string[] = [];
  if (scenario.source_dirty_before_apply) blockers.push("source_dirty_before_apply");
  if (scenario.force_missing_checkpoint) blockers.push("force_missing_checkpoint");
  return blockers;
}

function checkpointRefs(payload: Record<string, unknown> | undefined): string[] {
  if (!payload) return [];
  const direct = typeof payload.checkpoint_ref === "string" ? [payload.checkpoint_ref] : [];
  const worker = payload.worker && typeof payload.worker === "object" ? payload.worker as Record<string, unknown> : undefined;
  const workerCheckpoint = worker && typeof worker.checkpoint_ref === "string" ? [worker.checkpoint_ref] : [];
  return [...direct, ...workerCheckpoint];
}

function hasFailedWorker(events: ReplayLike["events"]): boolean {
  return (events ?? []).some((event) => {
    const worker = event.payload?.worker;
    return worker && typeof worker === "object" && (worker as Record<string, unknown>).status === "failed";
  });
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)];
}
