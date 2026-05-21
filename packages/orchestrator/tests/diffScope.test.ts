import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { listActualChangedFiles, validateDiffScope } from "../src/diffScope";

describe("diff scope validation", () => {
  test("accepts exact changed files inside allowed globs", () => {
    expect(validateDiffScope({
      actual_changed_files: ["README.md"],
      claimed_changed_files: ["README.md"],
      allowed_write_globs: ["README.md"],
      forbidden_write_globs: [".git/**", "node_modules/**"]
    })).toEqual({ ok: true, changed_files: ["README.md"] });
  });

  test("accepts directory prefixes and /** globs without shell expansion", () => {
    expect(validateDiffScope({
      actual_changed_files: ["packages/orchestrator/src/diffScope.ts", "docs/migration/task.md"],
      claimed_changed_files: ["packages/orchestrator", "docs/migration/**"],
      allowed_write_globs: ["packages/orchestrator", "docs/migration/**"],
      forbidden_write_globs: ["node_modules/**"]
    })).toEqual({
      ok: true,
      changed_files: ["packages/orchestrator/src/diffScope.ts", "docs/migration/task.md"]
    });
  });

  test("rejects changed files outside allowed globs", () => {
    expect(validateDiffScope({
      actual_changed_files: ["secrets.txt"],
      claimed_changed_files: ["README.md"],
      allowed_write_globs: ["README.md"],
      forbidden_write_globs: [".git/**", "node_modules/**"]
    })).toMatchObject({
      ok: false,
      failure_class: "diff_scope_failed",
      reason: "changed_file_outside_allowed_globs",
      changed_files: ["secrets.txt"]
    });
  });

  test("rejects changed files matched by forbidden globs", () => {
    expect(validateDiffScope({
      actual_changed_files: [".git/config"],
      claimed_changed_files: [".git/config"],
      allowed_write_globs: [".git/config"],
      forbidden_write_globs: [".git/**"]
    })).toMatchObject({
      ok: false,
      failure_class: "diff_scope_failed",
      reason: "changed_file_matches_forbidden_globs",
      changed_files: [".git/config"]
    });
  });

  test("rejects actual changes not claimed by the provider", () => {
    expect(validateDiffScope({
      actual_changed_files: ["README.md"],
      claimed_changed_files: [],
      allowed_write_globs: ["README.md"],
      forbidden_write_globs: []
    })).toMatchObject({
      ok: false,
      failure_class: "diff_scope_failed",
      reason: "changed_file_missing_provider_claim",
      changed_files: ["README.md"]
    });
  });

  test("accepts read-only tasks with no actual changes", () => {
    expect(validateDiffScope({
      actual_changed_files: [],
      claimed_changed_files: [],
      allowed_write_globs: [],
      forbidden_write_globs: [".git/**"]
    })).toEqual({ ok: true, changed_files: [] });
  });
});

describe("actual changed file discovery", () => {
  test("lists modified and untracked files from git status porcelain", () => {
    const worktree = mkdtempSync(join(tmpdir(), "waygent-diff-scope-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: worktree });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: worktree });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: worktree });
    writeFileSync(join(worktree, "README.md"), "before\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: worktree });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: worktree });

    writeFileSync(join(worktree, "README.md"), "after\n");
    mkdirSync(join(worktree, "src"), { recursive: true });
    writeFileSync(join(worktree, "src", "new.ts"), "export const value = 1;\n");

    expect(listActualChangedFiles(worktree)).toEqual(["README.md", "src/new.ts"]);
  });
});
