import type { AgentLensEvent, FailureClass, RunStatus } from "@waygent/contracts";
import { readEvents, readLatestRunId, rebuildRunSummary, runPaths } from "@waygent/lens-store";
import { projectFailureSummary, projectTrustReport } from "@waygent/lens-projectors";
export { buildRunEvent, nextRunEvent } from "./runEvents";

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
} {
  const status = statusRun(options);
  return {
    ...status,
    failures: projectFailureSummary(readEvents(runPaths(options.root, status.run_id).events))
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
  return {
    run_id: explanation.run_id,
    allowed_actions: explanation.blocked_by === "verification_failed" ? ["retry_with_evidence", "update_plan"] : ["inspect_run"],
    dry_run: options.dry_run ?? false
  };
}
