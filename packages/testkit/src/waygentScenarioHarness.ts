import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import type { ApplyReadinessProjection, ProviderAttempt, WaygentRunStateV2 } from "@waygent/contracts";
import { projectApplyReadinessFromState } from "@waygent/lens-projectors";

export type WaygentScenarioProviderFixture = "fake-success" | "malformed-provider" | "live-provider";
export type WaygentScenarioRunStatus = "trusted" | "failed";
export type WaygentScenarioApplyStatus = "not_applied" | "ready" | "not_ready" | "blocked" | "applied";

export interface NormalizedWaygentProviderAttempt {
  attempt_id: string;
  task_id: string;
  provider: string;
  stdout_ref: string | null;
  stderr_ref: string | null;
  worker_result_ref: string | null;
  exit_code: number | null;
  timed_out: boolean;
  failure_class: string | null;
}

export interface WaygentScenarioExpectedReplay {
  run_status: WaygentScenarioRunStatus;
  apply_status: WaygentScenarioApplyStatus;
  event_types: string[];
  total_events?: number;
  safe_wave?: string[];
  checkpoints?: string[];
  blockers?: string[];
  failure_classes?: string[];
  combined_patch_ref?: string | null;
  provider_attempts?: Array<Partial<NormalizedWaygentProviderAttempt>>;
}

export interface WaygentScenario {
  id: string;
  title: string;
  provider_fixture: WaygentScenarioProviderFixture;
  source_dirty_before_apply: boolean;
  force_missing_checkpoint: boolean;
  checkpoint_dry_run_conflict?: boolean;
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
  failure_classes?: string[];
  combined_patch_ref?: string | null;
  provider_attempts?: NormalizedWaygentProviderAttempt[];
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
    outcome?: string;
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
  run_state_v2?: WaygentRunStateV2 | null;
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
  if (raw.checkpoint_dry_run_conflict !== undefined && typeof raw.checkpoint_dry_run_conflict !== "boolean") {
    throw new Error(`${raw.id} checkpoint_dry_run_conflict must be boolean when set`);
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
  const state = replay.run_state_v2 ?? null;
  const applyReadiness = state ? projectApplyReadinessFromState(state) : null;
  const runStatus = state
    ? normalizeRunStatusFromState(state, events, options.force_missing_checkpoint)
    : normalizeRunStatusFromEvents(replay, events, options.force_missing_checkpoint);
  const checkpoints = options.force_missing_checkpoint
    ? []
    : state
      ? checkpointRefsFromState(state)
      : uniqueStrings(events.flatMap((event) => checkpointRefs(event.payload)));
  const normalized: NormalizedWaygentReplay = {
    run_status: runStatus,
    apply_status: options.apply_status ?? normalizeApplyStatus(replay.apply_state, applyReadiness),
    total_events: replay.summary?.total_events ?? events.length,
    safe_wave: replay.projection?.safe_wave ?? [],
    event_types: events.map((event) => String(event.event_type)),
    checkpoints
  };
  if (state) {
    normalized.combined_patch_ref = applyReadiness?.combined_patch_ref ?? null;
    normalized.provider_attempts = providerAttemptsFromState(state);
    const failureClasses = failureClassesFromState(state);
    if (failureClasses.length > 0) normalized.failure_classes = failureClasses;
  } else {
    const providerAttempts = providerAttemptsFromEvents(events);
    if (providerAttempts.length > 0) normalized.provider_attempts = providerAttempts;
  }
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
  const workspace = options.workspace ?? initScenarioSourceCheckout(`waygent-scenario-source-${scenario.id}-`);
  try {
    const runWaygent = await loadRunWaygent();
    const runOptions: RunWaygentOptionsLike = {
      root,
      run_id: options.run_id ?? `scenario_${scenario.id}`,
      plan: scenario.plan,
      workspace,
      ...providerOptions(scenario, options)
    };
    const result = await runWaygent(runOptions);
    const state = readScenarioRunState(root, runOptions.run_id);
    return {
      scenario,
      normalized: normalizeWaygentReplay({
        ...result,
        run_state_v2: state ? applyScenarioStateFaults(state, scenario) : null
      }, {
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

function initScenarioSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  writeFileSync(join(workspace, "README.md"), "fixture\n");
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

function isProviderFixture(value: unknown): value is WaygentScenarioProviderFixture {
  return value === "fake-success" || value === "malformed-provider" || value === "live-provider";
}

function normalizeApplyStatus(
  value: unknown,
  applyReadiness: ApplyReadinessProjection | null
): WaygentScenarioApplyStatus {
  if (applyReadiness) return applyReadiness.status;
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
  if (scenario.checkpoint_dry_run_conflict) blockers.push("checkpoint_dry_run_conflict");
  return blockers;
}

function checkpointRefs(payload: Record<string, unknown> | undefined): string[] {
  if (!payload) return [];
  const direct = typeof payload.checkpoint_ref === "string" ? [payload.checkpoint_ref] : [];
  const patch = typeof payload.patch_ref === "string" ? [payload.patch_ref] : [];
  const worker = payload.worker && typeof payload.worker === "object" ? payload.worker as Record<string, unknown> : undefined;
  const workerCheckpoint = worker && typeof worker.checkpoint_ref === "string" ? [worker.checkpoint_ref] : [];
  return [...direct, ...patch, ...workerCheckpoint];
}

function checkpointRefsFromState(state: WaygentRunStateV2): string[] {
  const refs = new Set<string>();
  const combined = combinedApplyEvidence(state);
  const combinedRefs = combined?.checkpoint_refs;
  if (Array.isArray(combinedRefs)) {
    for (const ref of combinedRefs) {
      if (typeof ref === "string" && ref.length > 0) refs.add(ref);
    }
  }
  for (const task of Object.values(state.tasks ?? {})) {
    for (const ref of task.checkpoint_refs ?? []) {
      if (ref.length > 0) refs.add(ref);
    }
  }
  return [...refs];
}

function providerAttemptsFromState(state: WaygentRunStateV2): NormalizedWaygentProviderAttempt[] {
  return (state.provider_attempts ?? []).map(normalizeProviderAttempt);
}

function failureClassesFromState(state: WaygentRunStateV2): string[] {
  return uniqueStrings(
    Object.values(state.tasks ?? {})
      .map((task) => task.latest_failure_class)
      .filter((value): value is string => typeof value === "string" && value.length > 0)
  );
}

function providerAttemptsFromEvents(events: ReplayLike["events"]): NormalizedWaygentProviderAttempt[] {
  const attempts: NormalizedWaygentProviderAttempt[] = [];
  for (const event of events ?? []) {
    const payloadAttempt = event.payload?.attempt;
    if (payloadAttempt && typeof payloadAttempt === "object") {
      attempts.push(normalizeProviderAttempt(payloadAttempt as Partial<ProviderAttempt>));
    }
  }
  return attempts;
}

function normalizeProviderAttempt(attempt: Partial<ProviderAttempt>): NormalizedWaygentProviderAttempt {
  return {
    attempt_id: stringOrEmpty(attempt.attempt_id),
    task_id: stringOrEmpty(attempt.task_id),
    provider: stringOrEmpty(attempt.provider),
    stdout_ref: stringOrNull(attempt.stdout_ref),
    stderr_ref: stringOrNull(attempt.stderr_ref),
    worker_result_ref: stringOrNull(attempt.worker_result_ref),
    exit_code: typeof attempt.exit_code === "number" ? attempt.exit_code : null,
    timed_out: attempt.timed_out === true,
    failure_class: stringOrNull(attempt.failure_class)
  };
}

function hasFailedWorker(events: ReplayLike["events"]): boolean {
  return (events ?? []).some((event) => {
    const worker = event.payload?.worker;
    if (!worker || typeof worker !== "object") return false;
    const status = (worker as Record<string, unknown>).status;
    return status === "failed" || status === "blocked";
  });
}

function normalizeRunStatusFromEvents(
  replay: ReplayLike,
  events: ReplayLike["events"],
  forceMissingCheckpoint: boolean | undefined
): WaygentScenarioRunStatus {
  return !forceMissingCheckpoint && replay.trust_report?.trust_status === "trusted" && !hasFailedWorker(events)
    ? "trusted"
    : "failed";
}

function normalizeRunStatusFromState(
  state: WaygentRunStateV2,
  events: ReplayLike["events"],
  forceMissingCheckpoint: boolean | undefined
): WaygentScenarioRunStatus {
  const audit = state.completion_audit as { status?: unknown } | null;
  return !forceMissingCheckpoint
    && audit?.status === "passed"
    && !hasFailedWorker(events)
    && (state.drift?.unrepaired_blockers ?? []).length === 0
    ? "trusted"
    : "failed";
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)];
}

function readScenarioRunState(root: string, runId: string | undefined): WaygentRunStateV2 | null {
  if (!runId) return null;
  const statePath = join(root, runId, "state.json");
  if (!existsSync(statePath)) return null;
  return JSON.parse(readFileSync(statePath, "utf8")) as WaygentRunStateV2;
}

function applyScenarioStateFaults(state: WaygentRunStateV2, scenario: WaygentScenario): WaygentRunStateV2 {
  if (!scenario.source_dirty_before_apply && !scenario.force_missing_checkpoint && !scenario.checkpoint_dry_run_conflict) return state;
  const next = structuredClone(state) as WaygentRunStateV2;
  if (scenario.source_dirty_before_apply) {
    addDriftBlocker(next, "source_dirty_before_apply");
    next.apply = { status: "blocked", reason: "source_dirty_before_apply" };
  }
  if (scenario.force_missing_checkpoint) {
    for (const task of Object.values(next.tasks)) task.checkpoint_refs = [];
    next.completion_audit = {
      ...(next.completion_audit ?? {}),
      status: "failed"
    };
    const combined = combinedApplyEvidence(next);
    if (combined) {
      combined.status = "failed";
      delete combined.patch_ref;
      delete combined.checkpoint_refs;
      combined.reason = "force_missing_checkpoint";
    }
    addDriftBlocker(next, "force_missing_checkpoint");
    next.apply = { status: "blocked", reason: "force_missing_checkpoint" };
  }
  if (scenario.checkpoint_dry_run_conflict) {
    for (const task of Object.values(next.tasks)) {
      task.status = "blocked";
      task.latest_failure_class = "needs_rebase";
      task.checkpoint_refs = [];
    }
    next.status = "blocked";
    next.lifecycle_outcome = "blocked";
    next.completion_audit = {
      ...(next.completion_audit ?? {}),
      status: "failed"
    };
    const combined = combinedApplyEvidence(next);
    if (combined) {
      combined.status = "failed";
      delete combined.patch_ref;
      delete combined.checkpoint_refs;
      combined.reason = "needs_rebase";
    }
    next.apply = { status: "blocked", reason: "needs_rebase" };
  }
  return next;
}

function addDriftBlocker(state: WaygentRunStateV2, reason: string): void {
  state.drift = state.drift ?? { last_checked_at: null, records: [], unrepaired_blockers: [] };
  state.drift.unrepaired_blockers = [
    ...(state.drift.unrepaired_blockers ?? []),
    { reason }
  ];
}

function combinedApplyEvidence(state: WaygentRunStateV2): Record<string, unknown> | undefined {
  const audit = state.completion_audit as { combined_apply_evidence?: Record<string, unknown> } | null;
  return audit?.combined_apply_evidence;
}

function stringOrEmpty(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}
