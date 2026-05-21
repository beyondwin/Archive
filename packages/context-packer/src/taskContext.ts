import type { TaskNode } from "@waygent/runway-control";
import type { RepoMapEntry } from "./repoMap";

export interface ContextPacket {
  included_paths: string[];
  excluded_paths: Array<{ path: string; reason: string }>;
  byte_limit: number;
  file_claims: TaskNode["file_claims"];
  verification_commands: string[];
  failure_evidence: string[];
}

export function selectTaskContext(
  task: TaskNode,
  repoMap: RepoMapEntry[],
  byteLimit: number,
  failureEvidence: string[] = [],
  verificationCommands: string[] = []
): ContextPacket {
  const seeds = new Set([...task.file_claims.map((claim) => claim.path), ...failureEvidence]);
  const included: string[] = [];
  const excluded: ContextPacket["excluded_paths"] = [];
  let used = 0;
  for (const entry of repoMap.sort((a, b) => a.path.localeCompare(b.path))) {
    const relevant = [...seeds].some((seed) => entry.path === seed || entry.path.startsWith(`${seed}/`) || seed.startsWith(entry.path));
    if (!relevant) {
      excluded.push({ path: entry.path, reason: "not task scoped" });
      continue;
    }
    if (used + entry.byte_size > byteLimit) {
      excluded.push({ path: entry.path, reason: "byte limit" });
      continue;
    }
    used += entry.byte_size;
    included.push(entry.path);
  }
  return {
    included_paths: included,
    excluded_paths: excluded,
    byte_limit: byteLimit,
    file_claims: task.file_claims,
    verification_commands: verificationCommands,
    failure_evidence: failureEvidence
  };
}
