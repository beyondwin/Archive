import { spawnSync } from "node:child_process";
import type { FileClaim } from "@waygent/runway-control";

export type SourceCheckoutStatus = "clean" | "dirty_related" | "dirty_unrelated";

export interface SourceCheckoutClassification {
  status: SourceCheckoutStatus;
  dirty_files: string[];
  related: string[];
  unrelated: string[];
}

export function classifySourceCheckout(workspace: string, claims: FileClaim[]): SourceCheckoutClassification {
  const result = spawnSync("git", ["status", "--porcelain"], {
    cwd: workspace,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  const dirty_files = result.status === 0
    ? result.stdout
      .split(/\r?\n/)
      .map((line) => line.slice(3).trim())
      .filter(Boolean)
    : [];
  const related = dirty_files.filter((file) => claims.some((claim) => samePathFamily(file, claim.path)));
  const unrelated = dirty_files.filter((file) => !related.includes(file));
  return {
    status: dirty_files.length === 0 ? "clean" : related.length > 0 ? "dirty_related" : "dirty_unrelated",
    dirty_files,
    related,
    unrelated
  };
}

function samePathFamily(left: string, right: string): boolean {
  const a = left.replace(/\/+$/, "");
  const b = right.replace(/\/+$/, "");
  return a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`);
}
