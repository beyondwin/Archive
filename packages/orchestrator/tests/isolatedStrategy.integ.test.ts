import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readlinkSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { prepareIsolatedStrategy } from "../src/isolatedStrategy";

const RUN = process.env.WAYGENT_RUN_INTEG_TESTS === "1";
const dscribe = RUN ? describe : describe.skip;

function makeWorkspace(): { workspace: string; cleanup: () => void } {
  const workspace = mkdtempSync(join(tmpdir(), "sp2-integ-"));
  writeFileSync(join(workspace, "bun.lock"), "");
  writeFileSync(
    join(workspace, "package.json"),
    JSON.stringify({
      name: "sp2-integ-root",
      private: true,
      workspaces: ["packages/*"]
    })
  );
  mkdirSync(join(workspace, "packages/foo"), { recursive: true });
  writeFileSync(
    join(workspace, "packages/foo/package.json"),
    JSON.stringify({ name: "@waygent/foo", version: "0.0.1", main: "index.js" })
  );
  writeFileSync(join(workspace, "packages/foo/index.js"), "module.exports = { value: 'main' };");
  return {
    workspace,
    cleanup: () => rmSync(workspace, { force: true, recursive: true })
  };
}

function copyAsWorktree(workspace: string): string {
  const worktree = mkdtempSync(join(tmpdir(), "sp2-wt-"));
  cpSync(workspace, worktree, { recursive: true, dereference: false });
  return worktree;
}

dscribe("isolatedStrategy (integration)", () => {
  const previousFrozen = process.env.WAYGENT_VERIFY_ISOLATION_FROZEN_LOCKFILE;
  beforeAll(() => {
    process.env.WAYGENT_VERIFY_ISOLATION_FROZEN_LOCKFILE = "0";
  });
  afterAll(() => {
    if (previousFrozen === undefined) delete process.env.WAYGENT_VERIFY_ISOLATION_FROZEN_LOCKFILE;
    else process.env.WAYGENT_VERIFY_ISOLATION_FROZEN_LOCKFILE = previousFrozen;
  });


  it("scenario A: cold cache prepares snapshot and resolves to worktree-local packages/*", () => {
    const { workspace, cleanup } = makeWorkspace();
    try {
      const worktree = copyAsWorktree(workspace);
      writeFileSync(join(worktree, "packages/foo/index.js"), "module.exports = { value: 'worker' };");

      const prepared = prepareIsolatedStrategy({ workspace, worktree });
      expect(prepared.evidence.isolation_status).toBe("prepared");
      expect(prepared.evidence.cache.hit).toBe(false);
      expect(prepared.evidence.isolated_packages).toContain("@waygent/foo");

      const linkPath = join(worktree, "node_modules/@waygent/foo");
      expect(existsSync(linkPath)).toBe(true);
      const target = readlinkSync(linkPath);
      const resolved = resolve(join(linkPath, ".."), target);
      expect(resolved.startsWith(worktree)).toBe(true);

      const indexContent = readFileSync(join(linkPath, "index.js"), "utf8");
      expect(indexContent).toContain("worker");

      prepared.cleanup();
    } finally {
      cleanup();
    }
  });

  it("scenario B: warm cache hit skips bun install", () => {
    const { workspace, cleanup } = makeWorkspace();
    try {
      const wt1 = copyAsWorktree(workspace);
      const first = prepareIsolatedStrategy({ workspace, worktree: wt1 });
      expect(first.evidence.cache.hit).toBe(false);
      first.cleanup();

      const wt2 = copyAsWorktree(workspace);
      const second = prepareIsolatedStrategy({ workspace, worktree: wt2 });
      expect(second.evidence.cache.hit).toBe(true);
      expect(second.evidence.isolation_status).toBe("prepared");
      second.cleanup();
    } finally {
      cleanup();
    }
  });

  it("scenario C: manifest drift triggers strict block", () => {
    const { workspace, cleanup } = makeWorkspace();
    try {
      const wt1 = copyAsWorktree(workspace);
      prepareIsolatedStrategy({ workspace, worktree: wt1 }).cleanup();

      mkdirSync(join(workspace, "packages/bar"), { recursive: true });
      writeFileSync(
        join(workspace, "packages/bar/package.json"),
        JSON.stringify({ name: "@waygent/bar", version: "0.0.1" })
      );

      const wt2 = copyAsWorktree(workspace);
      const drifted = prepareIsolatedStrategy({ workspace, worktree: wt2 });
      drifted.cleanup();
      rmSync(join(wt2, "packages/bar"), { force: true, recursive: true });
      const drifted2 = prepareIsolatedStrategy({ workspace, worktree: wt2 });
      expect(drifted2.evidence.isolation_status).toBe("unavailable");
      expect(drifted2.evidence.reason).toContain("manifest_drift");
      drifted2.cleanup();
    } finally {
      cleanup();
    }
  });

  it("scenario D: bun install failure surfaces as strict block", () => {
    const { workspace, cleanup } = makeWorkspace();
    try {
      writeFileSync(join(workspace, "package.json"), "{not valid json");
      const worktree = copyAsWorktree(workspace);
      const prepared = prepareIsolatedStrategy({ workspace, worktree });
      expect(prepared.evidence.isolation_status).toBe("unavailable");
      expect(prepared.evidence.reason).toContain("isolation_unavailable.");
      prepared.cleanup();
    } finally {
      cleanup();
    }
  });

  it("scenario E: cleanup removes worktree links but preserves snapshot", () => {
    const { workspace, cleanup } = makeWorkspace();
    try {
      const worktree = copyAsWorktree(workspace);
      const prepared = prepareIsolatedStrategy({ workspace, worktree });
      const snapshotDir = prepared.evidence.cache.snapshot_path!;
      expect(existsSync(snapshotDir)).toBe(true);
      prepared.cleanup();
      expect(existsSync(join(worktree, "node_modules"))).toBe(false);
      expect(existsSync(snapshotDir)).toBe(true);
    } finally {
      cleanup();
    }
  });
});
