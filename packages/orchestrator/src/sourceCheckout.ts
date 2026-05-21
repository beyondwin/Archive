import { spawnSync } from "node:child_process";
import type { WaygentSourcePreflight } from "@waygent/contracts";
import type { FileClaim } from "@waygent/runway-control";

export type SourceCheckoutStatus = WaygentSourcePreflight["status"];

export type SourceCheckoutClassification = WaygentSourcePreflight;

export function classifySourceCheckout(workspace: string, claims: FileClaim[]): SourceCheckoutClassification {
  const checked_at = new Date().toISOString();
  const result = spawnSync("git", ["status", "--porcelain", "--untracked-files=all"], {
    cwd: workspace,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (result.status !== 0) {
    return {
      status: "dirty_related",
      dirty_files: ["git_status_failed"],
      related: ["git_status_failed"],
      unrelated: [],
      checked_at,
      reason: "dirty_source_checkout",
      decision_packet_ref: null
    };
  }
  const dirty_files = result.status === 0
    ? result.stdout
      .split(/\r?\n/)
      .map((line) => line.slice(3).trim())
      .filter(Boolean)
    : [];
  const related = dirty_files.filter((file) => claims.some((claim) => samePathFamily(file, claim.path)));
  const unrelated = dirty_files.filter((file) => !related.includes(file));
  const status = dirty_files.length === 0 ? "clean" : related.length > 0 ? "dirty_related" : "dirty_unrelated";
  return {
    status,
    dirty_files,
    related,
    unrelated,
    checked_at,
    reason: status === "clean"
      ? null
      : status === "dirty_related"
        ? "dirty_source_checkout"
        : "dirty_unrelated_source_checkout",
    decision_packet_ref: null
  };
}

function samePathFamily(left: string, right: string): boolean {
  const a = left.replace(/\/+$/, "");
  const b = right.replace(/\/+$/, "");
  return a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`);
}
