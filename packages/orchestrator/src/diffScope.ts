import { spawnSync } from "node:child_process";

export interface DiffScopeInput {
  actual_changed_files: string[];
  claimed_changed_files: string[];
  allowed_write_globs: string[];
  forbidden_write_globs: string[];
}

export type DiffScopeResult =
  | { ok: true; changed_files: string[] }
  | {
    ok: false;
    failure_class: "diff_scope_failed";
    reason:
      | "changed_file_outside_allowed_globs"
      | "changed_file_matches_forbidden_globs"
      | "changed_file_missing_provider_claim";
    changed_files: string[];
    violating_files: string[];
    allowed_write_globs: string[];
    provider_claimed_changed_files: string[];
  };

export function listActualChangedFiles(worktree: string): string[] {
  const result = spawnSync("git", ["status", "--porcelain", "--untracked-files=all"], {
    cwd: worktree,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (result.status !== 0) return [];
  return result.stdout
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean)
    .map((line) => {
      const path = line.slice(3).trim();
      const renameTarget = path.split(" -> ").at(-1);
      return normalizePath(renameTarget ?? path);
    })
    .filter(Boolean)
    .sort();
}

export function validateDiffScope(input: DiffScopeInput): DiffScopeResult {
  const changed_files = input.actual_changed_files.map(normalizePath).filter(Boolean);
  const forbidden = changed_files.filter((file) => matchesAny(file, input.forbidden_write_globs));
  if (forbidden.length > 0) {
    return failed("changed_file_matches_forbidden_globs", changed_files, forbidden, input);
  }

  const outsideAllowed = changed_files.filter((file) => !matchesAny(file, input.allowed_write_globs));
  if (outsideAllowed.length > 0) {
    return failed("changed_file_outside_allowed_globs", changed_files, outsideAllowed, input);
  }

  const missingClaim = changed_files.filter((file) => !matchesAny(file, input.claimed_changed_files));
  if (missingClaim.length > 0) {
    return failed("changed_file_missing_provider_claim", changed_files, missingClaim, input);
  }

  return { ok: true, changed_files };
}

function failed(
  reason: Exclude<DiffScopeResult, { ok: true }>["reason"],
  changed_files: string[],
  violating_files: string[],
  input: DiffScopeInput
): Exclude<DiffScopeResult, { ok: true }> {
  return {
    ok: false,
    failure_class: "diff_scope_failed",
    reason,
    changed_files,
    violating_files,
    allowed_write_globs: input.allowed_write_globs.map(normalizePath).filter(Boolean),
    provider_claimed_changed_files: input.claimed_changed_files.map(normalizePath).filter(Boolean)
  };
}

function matchesAny(file: string, patterns: string[]): boolean {
  return patterns.some((pattern) => matchesPattern(file, pattern));
}

function matchesPattern(file: string, pattern: string): boolean {
  const normalizedFile = normalizePath(file);
  const normalizedPattern = normalizePath(pattern);
  if (!normalizedPattern) return false;
  if (normalizedPattern.endsWith("/**")) {
    const prefix = normalizedPattern.slice(0, -"/**".length);
    return normalizedFile === prefix || normalizedFile.startsWith(`${prefix}/`);
  }
  return normalizedFile === normalizedPattern || normalizedFile.startsWith(`${normalizedPattern}/`);
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\.\/+/, "").replace(/\/+$/, "");
}
