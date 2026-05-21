import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { validateContract, type WaygentRunStateV2 } from "@waygent/contracts";

export type { WaygentRunStateV2 } from "@waygent/contracts";

export type RunStateV2ReadResult =
  | { status: "ok"; state: WaygentRunStateV2 }
  | { status: "missing"; reason: "missing_run_state_v2" }
  | { status: "unsupported"; reason: "unsupported_run_state"; schema: unknown }
  | { status: "invalid"; reason: "invalid_run_state_v2"; error: string };

export function runStatePath(root: string, runId: string): string {
  return join(root, runId, "state.json");
}

export function hasRunState(root: string, runId: string): boolean {
  return existsSync(runStatePath(root, runId));
}

export function writeRunStateV2(root: string, state: WaygentRunStateV2): void {
  const validated = validateContract<WaygentRunStateV2>("waygent.run_state.v2", state);
  mkdirSync(join(root, state.run_id), { recursive: true });
  writeFileSync(runStatePath(root, state.run_id), `${JSON.stringify(validated, null, 2)}\n`);
}

export function readRunStateV2(root: string, runId: string): WaygentRunStateV2 {
  const result = readRunStateV2Result(root, runId);
  if (result.status === "ok") return result.state;
  throw new Error(`run ${runId} has ${result.reason}`);
}

export function readRunStateV2Result(root: string, runId: string): RunStateV2ReadResult {
  const path = runStatePath(root, runId);
  if (!existsSync(path)) return { status: "missing", reason: "missing_run_state_v2" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8")) as unknown;
  } catch (error) {
    return { status: "invalid", reason: "invalid_run_state_v2", error: error instanceof Error ? error.message : String(error) };
  }
  const schema = parsed && typeof parsed === "object" ? (parsed as { schema?: unknown }).schema : undefined;
  if (schema !== "waygent.run_state.v2") return { status: "unsupported", reason: "unsupported_run_state", schema };
  try {
    return { status: "ok", state: validateContract<WaygentRunStateV2>("waygent.run_state.v2", parsed) };
  } catch (error) {
    return { status: "invalid", reason: "invalid_run_state_v2", error: error instanceof Error ? error.message : String(error) };
  }
}
