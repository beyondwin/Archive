import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { WaygentRunStateV2 } from "@waygent/contracts";
import type { ExecutionMode, ProviderName } from "./executionProfile";

export type { WaygentRunStateV2 } from "@waygent/contracts";

export type WaygentTaskRunStatus = "pending" | "running" | "completed" | "verified" | "failed" | "blocked";
export type WaygentRunLifecycleStatus = "created" | "running" | "blocked" | "failed" | "completed";
export type WaygentApplyStatus = "not_applied" | "blocked" | "applied";

export interface WaygentRunState {
  schema: "waygent.run_state.v1";
  run_id: string;
  workspace: string;
  worktree: string;
  status: WaygentRunLifecycleStatus;
  provider: ProviderName;
  execution_mode: ExecutionMode;
  tasks: Array<{ id: string; status: WaygentTaskRunStatus; checkpoint_ref?: string; failure_class?: string }>;
  completion_audit: null | { status: "passed" | "failed"; commands: string[]; evidence_events: string[] };
  apply: { status: WaygentApplyStatus; reason?: string };
}

export function runStatePath(root: string, runId: string): string {
  return join(root, runId, "state.json");
}

export function writeRunState(root: string, state: WaygentRunState): void {
  mkdirSync(join(root, state.run_id), { recursive: true });
  writeFileSync(runStatePath(root, state.run_id), `${JSON.stringify(state, null, 2)}\n`);
}

export function readRunState(root: string, runId: string): WaygentRunState {
  return JSON.parse(readFileSync(runStatePath(root, runId), "utf8")) as WaygentRunState;
}

export function hasRunState(root: string, runId: string): boolean {
  return existsSync(runStatePath(root, runId));
}

export function writeRunStateV2(root: string, state: WaygentRunStateV2): void {
  mkdirSync(join(root, state.run_id), { recursive: true });
  writeFileSync(runStatePath(root, state.run_id), `${JSON.stringify(state, null, 2)}\n`);
}

export function readRunStateV2(root: string, runId: string): WaygentRunStateV2 {
  const parsed = JSON.parse(readFileSync(runStatePath(root, runId), "utf8")) as WaygentRunStateV2;
  if (parsed.schema !== "waygent.run_state.v2") {
    throw new Error(`run ${runId} is not waygent.run_state.v2`);
  }
  return parsed;
}
