import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { AgentLensEvent } from "@waygent/contracts";
import { validateContract } from "@waygent/contracts";

export function appendEvent(path: string, event: AgentLensEvent): void {
  validateContract("agentlens.event.v3", event);
  const line = JSON.stringify(event);
  if (!line || line === "{}") throw new Error("event journal refuses empty payloads");
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${line}\n`, { flag: "a" });
}

export function readEvents(path: string): AgentLensEvent[] {
  try {
    const text = readFileSync(path, "utf8");
    return text
      .split("\n")
      .filter(Boolean)
      .map((line) => validateContract<AgentLensEvent>("agentlens.event.v3", JSON.parse(line)));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

export function nextSequence(events: AgentLensEvent[]): number {
  return events.reduce((max, event) => Math.max(max, event.sequence), 0) + 1;
}
