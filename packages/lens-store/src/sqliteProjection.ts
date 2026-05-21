import { existsSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { Database } from "bun:sqlite";
import type { AgentLensEvent } from "@waygent/contracts";
import { rebuildRunSummary, type RunSummary } from "./projection";

export function rebuildProjectionCache(path: string, events: AgentLensEvent[]): RunSummary {
  mkdirSync(dirname(path), { recursive: true });
  const db = new Database(path);
  db.run("create table if not exists run_summary (run_id text primary key, json text not null)");
  db.run("delete from run_summary");
  const summary = rebuildRunSummary(events);
  db.run("insert into run_summary values (?, ?)", [summary.run_id, JSON.stringify(summary)]);
  db.close();
  return summary;
}

export function readProjectionCache(path: string, fallbackEvents: AgentLensEvent[] = []): RunSummary {
  if (!existsSync(path)) return rebuildRunSummary(fallbackEvents);
  const db = new Database(path);
  try {
    const row = db.query<{ json: string }, []>("select json from run_summary limit 1").get();
    return row ? JSON.parse(row.json) as RunSummary : rebuildRunSummary(fallbackEvents);
  } catch {
    return rebuildRunSummary(fallbackEvents);
  } finally {
    db.close();
  }
}
