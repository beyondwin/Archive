import { describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { captureWorktreePatch } from "../src/patchCapture";

function makeRepo(): string {
  const root = mkdtempSync(join(tmpdir(), "waygent-patch-"));
  spawnSync("git", ["init", "-q", "-b", "main"], { cwd: root });
  spawnSync("git", ["config", "user.email", "test@test"], { cwd: root });
  spawnSync("git", ["config", "user.name", "test"], { cwd: root });
  writeFileSync(join(root, "a.txt"), "one\n");
  spawnSync("git", ["add", "a.txt"], { cwd: root });
  spawnSync("git", ["commit", "-q", "-m", "init"], { cwd: root });
  return root;
}

describe("captureWorktreePatch", () => {
  test("returns null when no changes vs main", () => {
    const root = makeRepo();
    try {
      expect(captureWorktreePatch({ worktree: root, base: "main" })).toBeNull();
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("returns patch text + sha256 + byte length when worktree is dirty", () => {
    const root = makeRepo();
    try {
      writeFileSync(join(root, "a.txt"), "one\ntwo\n");
      const captured = captureWorktreePatch({ worktree: root, base: "main" });
      expect(captured).not.toBeNull();
      expect(captured!.patch).toContain("a.txt");
      expect(captured!.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(captured!.byteLength).toBe(Buffer.byteLength(captured!.patch));
      expect(captured!.truncatedWarning).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("flags patch_truncated_warning when patch exceeds 1MB", () => {
    const root = makeRepo();
    try {
      const big = "x".repeat(1_200_000);
      writeFileSync(join(root, "b.txt"), big);
      spawnSync("git", ["add", "b.txt"], { cwd: root });
      const captured = captureWorktreePatch({ worktree: root, base: "main" });
      expect(captured).not.toBeNull();
      expect(captured!.byteLength).toBeGreaterThan(1_048_576);
      expect(captured!.truncatedWarning).toBe(true);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
