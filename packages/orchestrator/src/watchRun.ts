import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { readLatestRunId, runPaths } from "@waygent/lens-store";
import type { RunCommandOptions } from "./runCommands";

export type WatchFilter = "all" | "task_transition" | "failure" | "cost";

export interface WatchRunOptions extends RunCommandOptions {
  json?: boolean;
  filter?: WatchFilter;
  timeout_ms?: number;
}

export interface WatchRunResult {
  run_id: string;
  terminal: boolean;
  lines: string[];
}

export function watchRun(options: WatchRunOptions): WatchRunResult {
  const runId = resolveWatchRunId(options);
  const paths = runPaths(options.root, runId);
  const events = readRawEvents(paths.events).filter((event) => matchesFilter(event, options.filter ?? "all"));
  const lines = events.map((event) => options.json ? JSON.stringify(event) : humanLine(event));
  return {
    run_id: runId,
    terminal: terminalState(paths.root),
    lines
  };
}

function resolveWatchRunId(options: RunCommandOptions): string {
  if (options.run) return options.run;
  if (options.last) {
    const latest = readLatestRunId(options.root);
    if (latest) return latest;
  }
  throw new Error("run id required; pass --run <id> or --last");
}

function readRawEvents(path: string): Array<Record<string, unknown>> {
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line) as Record<string, unknown>;
      } catch {
        return { event_type: "invalid_event", raw: line };
      }
    });
}

function matchesFilter(event: Record<string, unknown>, filter: WatchFilter): boolean {
  const type = String(event.event_type ?? "");
  if (filter === "all") return true;
  if (filter === "task_transition") return type.startsWith("runway.") && /task|worker|verification|checkpoint/.test(type);
  if (filter === "failure") return event.outcome === "failed" || event.outcome === "blocked" || /failed|blocked/.test(type);
  if (filter === "cost") return type.startsWith("platform.cost_");
  return true;
}

function humanLine(event: Record<string, unknown>): string {
  return [
    event.occurred_at ?? "",
    event.event_type ?? "unknown",
    event.outcome ?? "unknown",
    event.summary ?? ""
  ].filter(Boolean).join(" ");
}

function terminalState(runRoot: string): boolean {
  const path = join(runRoot, "state.json");
  if (!existsSync(path)) return false;
  try {
    const state = JSON.parse(readFileSync(path, "utf8")) as { status?: unknown };
    return ["completed", "blocked", "failed", "applied"].includes(String(state.status));
  } catch {
    return false;
  }
}
