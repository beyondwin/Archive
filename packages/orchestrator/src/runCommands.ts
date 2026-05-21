import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import type { AgentLensEvent, FailureClass, RunStatus } from "@waygent/contracts";
import { appendEvent, readEvents, readLatestRunId, rebuildRunSummary, runPaths } from "@waygent/lens-store";
import { projectFailureSummary, projectTrustReport } from "@waygent/lens-projectors";
import { hasRunState, readRunState, writeRunState, type WaygentRunState } from "./runState";
export { buildRunEvent, nextRunEvent } from "./runEvents";
import { nextRunEvent } from "./runEvents";

export interface RunCommandOptions {
  root: string;
  run?: string;
  last?: boolean;
}

export interface RunStatusView {
  run_id: string;
  status: RunStatus;
  total_events: number;
  last_event_type: string | null;
  trust_status: string;
}

export function resolveRunId(options: RunCommandOptions): string {
  if (options.run) return options.run;
  if (options.last) {
    const latest = readLatestRunId(options.root);
    if (latest) return latest;
  }
  throw new Error("run id required; pass --run <id> or --last");
}

export function statusRun(options: RunCommandOptions): RunStatusView {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  const summary = rebuildRunSummary(events);
  const trust = projectTrustReport(events);
  const blocked = events.some((event) => event.outcome === "blocked");
  const failed = events.some((event) => event.outcome === "failed");
  const status: RunStatus = blocked ? "blocked" : failed ? "failed" : trust.trust_status === "trusted" ? "completed" : "running";
  return {
    run_id: runId,
    status,
    total_events: summary.total_events,
    last_event_type: summary.last_event_type,
    trust_status: trust.trust_status
  };
}

export function eventsRun(options: RunCommandOptions): { run_id: string; total_events: number; events: AgentLensEvent[] } {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  return { run_id: runId, total_events: events.length, events };
}

export function inspectRun(options: RunCommandOptions): RunStatusView & {
  failures: ReturnType<typeof projectFailureSummary>;
  state?: WaygentRunState;
} {
  const status = statusRun(options);
  return {
    ...status,
    failures: projectFailureSummary(readEvents(runPaths(options.root, status.run_id).events)),
    ...(hasRunState(options.root, status.run_id) ? { state: readRunState(options.root, status.run_id) } : {})
  };
}

export function explainRun(options: RunCommandOptions): { run_id: string; blocked_by: FailureClass | "unknown" | null; summary: string } {
  const runId = resolveRunId(options);
  const events = readEvents(runPaths(options.root, runId).events);
  const failure = projectFailureSummary(events)[0] ?? null;
  return {
    run_id: runId,
    blocked_by: failure?.failure_class ?? null,
    summary: failure ? `${failure.task_id} blocked by ${failure.failure_class}` : "no active failure barrier"
  };
}

export function resumeRun(options: RunCommandOptions & { dry_run?: boolean }): { run_id: string; allowed_actions: string[]; dry_run: boolean } {
  const explanation = explainRun(options);
  if (hasRunState(options.root, explanation.run_id)) {
    const state = readRunState(options.root, explanation.run_id);
    if (state.status === "completed") {
      return {
        run_id: explanation.run_id,
        allowed_actions: ["inspect_run", "apply_verified_checkpoint"],
        dry_run: options.dry_run ?? false
      };
    }
  }
  return {
    run_id: explanation.run_id,
    allowed_actions: explanation.blocked_by === "verification_failed" ? ["retry_with_evidence", "update_plan"] : ["inspect_run"],
    dry_run: options.dry_run ?? false
  };
}

export function applyRun(options: RunCommandOptions & { workspace: string }): {
  command: "apply";
  run_id: string;
  status: "blocked" | "applied";
  reason?: string;
} {
  const runId = resolveRunId(options);
  const paths = runPaths(options.root, runId);
  if (isDirtySourceCheckout(options.workspace)) {
    appendEvent(paths.events, nextRunEvent(paths.events, {
      run_id: runId,
      event_type: "runway.apply_blocked",
      phase: "apply",
      outcome: "blocked",
      summary: "Apply blocked by dirty source checkout.",
      payload: { reason: "dirty_source_checkout" },
      trust_impact: "requires_review"
    }));
    if (hasRunState(options.root, runId)) {
      const state = readRunState(options.root, runId);
      writeRunState(options.root, { ...state, apply: { status: "blocked", reason: "dirty_source_checkout" } });
    }
    return { command: "apply", run_id: runId, status: "blocked", reason: "dirty_source_checkout" };
  }

  const checkpointRef = hasRunState(options.root, runId)
    ? readRunState(options.root, runId).tasks.find((task) => task.checkpoint_ref)?.checkpoint_ref
    : undefined;
  appendEvent(paths.events, nextRunEvent(paths.events, {
    run_id: runId,
    event_type: "runway.apply_completed",
    phase: "apply",
    outcome: "success",
    summary: "Verified checkpoint applied.",
    payload: { checkpoint_ref: checkpointRef ?? null }
  }));
  if (hasRunState(options.root, runId)) {
    const state = readRunState(options.root, runId);
    writeRunState(options.root, { ...state, status: "completed", apply: { status: "applied" } });
  }
  return { command: "apply", run_id: runId, status: "applied" };
}

function isDirtySourceCheckout(workspace: string): boolean {
  const gitStatus = spawnSync("git", ["status", "--porcelain"], {
    cwd: workspace,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (gitStatus.status === 0) {
    return gitStatus.stdout.trim().length > 0;
  }
  return readdirSync(workspace).some((entry) => !entry.startsWith(".git"));
}
