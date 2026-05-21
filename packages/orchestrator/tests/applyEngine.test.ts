import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { applyVerifiedCheckpoint } from "../src/applyEngine";

describe("Waygent apply engine", () => {
  test("refuses dirty source and applies clean checkpoint patches", async () => {
    const source = mkdtempSync(join(tmpdir(), "waygent-apply-source-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: source });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: source });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: source });
    writeFileSync(join(source, "README.md"), "before\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: source });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: source });

    const patch = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-before\n+after\n";
    const result = await applyVerifiedCheckpoint({ source, patch, post_apply_commands: ["grep after README.md"] });

    expect(result.status).toBe("applied");
  });

  test("reports patch dry-run failure before mutation", async () => {
    const source = mkdtempSync(join(tmpdir(), "waygent-apply-dry-run-source-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: source });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: source });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: source });
    writeFileSync(join(source, "README.md"), "different\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: source });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: source });

    const patch = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-before\n+after\n";
    expect(await applyVerifiedCheckpoint({ source, patch, post_apply_commands: ["grep after README.md"] })).toMatchObject({
      status: "blocked",
      reason: "patch_dry_run_failed"
    });
  });

  test("reports post-apply verification failure", async () => {
    const source = mkdtempSync(join(tmpdir(), "waygent-post-apply-source-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: source });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: source });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: source });
    writeFileSync(join(source, "README.md"), "before\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: source });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: source });

    const patch = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-before\n+after\n";
    expect(await applyVerifiedCheckpoint({ source, patch, post_apply_commands: ["grep missing README.md"] })).toMatchObject({
      status: "failed",
      reason: "post_apply_verification_failed"
    });
  });
});
