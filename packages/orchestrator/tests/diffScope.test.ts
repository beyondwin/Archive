import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { listActualChangedFiles, validateDiffScope } from "../src/diffScope";
import { runWaygent } from "../src/orchestrator";
import { readRunStateV2 } from "../src/runState";

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

describe("orchestrator diff scope checkpoint gate", () => {
  test("passes dependency checkpoint refs into dependent task packets", async () => {
    const workspace = initSourceCheckout("waygent-diff-scope-dependent-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-diff-scope-dependent-"));
    const dependentPlan = `
\`\`\`yaml waygent-task
id: task_base
title: Create base file
dependencies: []
file_claims:
  - path: base.txt
    mode: owned
risk: low
verify:
  - test -f base.txt
\`\`\`
\`\`\`yaml waygent-task
id: task_dependent
title: Create dependent file
dependencies: [task_base]
file_claims:
  - path: dependent.txt
    mode: owned
risk: low
verify:
  - test -f dependent.txt
\`\`\`
`;

    await runWaygent({
      root,
      workspace,
      run_id: "run_dependent",
      plan: dependentPlan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_dependent");
    const packetPath = state.tasks.task_dependent?.task_packet_path;
    expect(packetPath).toBeTruthy();
    const packet = JSON.parse(readFileSync(packetPath!, "utf8")) as { checkpoint_inputs?: string[] };
    expect(packet.checkpoint_inputs).toEqual(["artifacts/checkpoints/task_base/candidate_task_base.json"]);
  });

  test("blocks checkpoint sealing when actual worktree changes escape allowed scope", async () => {
    const workspace = initSourceCheckout("waygent-diff-scope-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-diff-scope-run-"));
    const leakingPlan = `
\`\`\`yaml waygent-task
id: task_scope
title: Create file and leak another
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: low
verify:
  - test -f a.txt && printf leak > secrets.txt
\`\`\`
`;

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_diff_scope",
      plan: leakingPlan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_diff_scope");
    expect(state.tasks.task_scope).toMatchObject({
      status: "blocked",
      latest_failure_class: "diff_scope_failed",
      checkpoint_refs: []
    });
    expect(result.events.find((event) => event.event_type === "runway.diff_scope_result")).toMatchObject({
      outcome: "blocked",
      payload: {
        task_id: "task_scope",
        failure_class: "diff_scope_failed",
        reason: "changed_file_outside_allowed_globs",
        changed_files: ["a.txt", "secrets.txt"]
      }
    });
  });
});

function initSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "fixture\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
  return workspace;
}
