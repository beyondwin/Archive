import { join } from "node:path";

export interface RunPaths {
  root: string;
  events: string;
  artifacts: string;
  cache: string;
}

export function runPaths(root: string, runId: string): RunPaths {
  const runRoot = join(root, runId);
  return {
    root: runRoot,
    events: join(runRoot, "events.jsonl"),
    artifacts: join(runRoot, "artifacts"),
    cache: join(runRoot, "projection.sqlite")
  };
}
