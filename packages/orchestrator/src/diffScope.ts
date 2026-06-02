import { spawnSync } from "node:child_process";
import type { ExpectedGeneratedOutput } from "./generatedOutputs";

export interface DiffScopeInput {
  actual_changed_files: string[];
  claimed_changed_files: string[];
  allowed_write_globs: string[];
  forbidden_write_globs: string[];
  expected_generated_outputs?: ExpectedGeneratedOutput[];
}

export type ScopeFailureKind =
  | "generated_artifact_unclaimed"
  | "provider_overreach"
  | "provider_claim_gap"
  | "forbidden_write";

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
    scope_failure_kind: ScopeFailureKind;
    recommended_scope_amendments: Array<{
      path: string;
      mode: "owned";
      reason: string;
      evidence_refs: string[];
    }>;
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
    return failed("changed_file_matches_forbidden_globs", "forbidden_write", changed_files, forbidden, input);
  }

  const outsideAllowed = changed_files.filter((file) => !matchesAny(file, input.allowed_write_globs));
  if (outsideAllowed.length > 0) {
    const expected = input.expected_generated_outputs ?? [];
    const generated = outsideAllowed.filter((file) => matchesGeneratedOutput(file, expected));
    return failed(
      "changed_file_outside_allowed_globs",
      generated.length > 0 ? "generated_artifact_unclaimed" : "provider_overreach",
      changed_files,
      outsideAllowed,
      input
    );
  }

  const missingClaim = changed_files.filter((file) => !matchesAny(file, input.claimed_changed_files));
  if (missingClaim.length > 0) {
    return failed("changed_file_missing_provider_claim", "provider_claim_gap", changed_files, missingClaim, input);
  }

  return { ok: true, changed_files };
}

function failed(
  reason: Exclude<DiffScopeResult, { ok: true }>["reason"],
  scope_failure_kind: ScopeFailureKind,
  changed_files: string[],
  violating_files: string[],
  input: DiffScopeInput
): Exclude<DiffScopeResult, { ok: true }> {
  const expected = input.expected_generated_outputs ?? [];
  return {
    ok: false,
    failure_class: "diff_scope_failed",
    reason,
    changed_files,
    violating_files,
    allowed_write_globs: input.allowed_write_globs.map(normalizePath).filter(Boolean),
    provider_claimed_changed_files: input.claimed_changed_files.map(normalizePath).filter(Boolean),
    scope_failure_kind,
    recommended_scope_amendments: scope_failure_kind === "generated_artifact_unclaimed"
      ? violating_files.map((file) => ({
        path: file,
        mode: "owned" as const,
        reason: "generated artifact is outside task writable claims",
        evidence_refs: amendmentEvidenceFor(file, expected)
      }))
      : []
  };
}

function matchesAny(file: string, patterns: string[]): boolean {
  return patterns.some((pattern) => matchesPattern(file, pattern));
}

function matchesGeneratedOutput(file: string, outputs: ExpectedGeneratedOutput[]): boolean {
  return outputs.some((output) => matchesPattern(file, output.path_glob));
}

function amendmentEvidenceFor(file: string, outputs: ExpectedGeneratedOutput[]): string[] {
  return outputs
    .filter((output) => matchesPattern(file, output.path_glob))
    .flatMap((output) => output.evidence_refs);
}

function matchesPattern(file: string, pattern: string): boolean {
  const normalizedFile = normalizePath(file);
  const normalizedPattern = normalizePath(pattern);
  if (!normalizedPattern) return false;
  if (/[?*[\]]/.test(normalizedPattern) && !normalizedPattern.endsWith("/**")) {
    return globToRegExp(normalizedPattern).test(normalizedFile);
  }
  if (normalizedPattern.endsWith("/**")) {
    const prefix = normalizedPattern.slice(0, -"/**".length);
    return normalizedFile === prefix || normalizedFile.startsWith(`${prefix}/`);
  }
  return normalizedFile === normalizedPattern || normalizedFile.startsWith(`${normalizedPattern}/`);
}

function globToRegExp(pattern: string): RegExp {
  const escaped = pattern
    .split("*")
    .map((part) => part.replace(/[.+^${}()|[\]\\]/g, "\\$&"))
    .join("[^/]*");
  return new RegExp(`^${escaped}$`);
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\.\/+/, "").replace(/\/+$/, "");
}
