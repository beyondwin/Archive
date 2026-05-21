import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { classifySourceCheckout } from "../src/sourceCheckout";

function initSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "clean\n");
  mkdirSync(join(workspace, "src"), { recursive: true });
  writeFileSync(join(workspace, "src", "app.ts"), "clean\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
  return workspace;
}

describe("source checkout classification", () => {
  test("returns a clean durable preflight record", () => {
    const workspace = initSourceCheckout("waygent-source-clean-");

    expect(classifySourceCheckout(workspace, [{ path: "README.md", mode: "owned" }])).toMatchObject({
      status: "clean",
      dirty_files: [],
      related: [],
      unrelated: [],
      reason: null,
      decision_packet_ref: null
    });
    expect(classifySourceCheckout(workspace, [{ path: "README.md", mode: "owned" }]).checked_at).toMatch(
      /^\d{4}-\d{2}-\d{2}T/
    );
  });

  test("classifies dirty files against task file claims", () => {
    const workspace = initSourceCheckout("waygent-source-dirty-");
    writeFileSync(join(workspace, "README.md"), "dirty\n");
    mkdirSync(join(workspace, "tmp"), { recursive: true });
    writeFileSync(join(workspace, "tmp", "scratch.txt"), "scratch\n");

    expect(classifySourceCheckout(workspace, [{ path: "README.md", mode: "owned" }])).toMatchObject({
      status: "dirty_related",
      related: ["README.md"],
      reason: "dirty_source_checkout",
      decision_packet_ref: null
    });
    expect(classifySourceCheckout(workspace, [{ path: "src/app.ts", mode: "owned" }])).toMatchObject({
      status: "dirty_unrelated",
      unrelated: ["README.md", "tmp/scratch.txt"],
      reason: "dirty_unrelated_source_checkout",
      decision_packet_ref: null
    });
  });

  test("treats nested dirty paths as related to parent claims", () => {
    const workspace = initSourceCheckout("waygent-source-nested-");
    writeFileSync(join(workspace, "src", "app.ts"), "dirty\n");

    expect(classifySourceCheckout(workspace, [{ path: "src", mode: "owned" }])).toMatchObject({
      status: "dirty_related",
      dirty_files: ["src/app.ts"],
      related: ["src/app.ts"],
      reason: "dirty_source_checkout"
    });
  });

  test("conservatively blocks when git status cannot be read", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-source-not-git-"));
    writeFileSync(join(workspace, "README.md"), "untracked\n");

    expect(classifySourceCheckout(workspace, [{ path: "README.md", mode: "owned" }])).toMatchObject({
      status: "dirty_related",
      dirty_files: ["git_status_failed"],
      related: ["git_status_failed"],
      unrelated: [],
      reason: "dirty_source_checkout",
      decision_packet_ref: null
    });
  });
});
