import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { computeCacheKey } from "../src/isolatedStrategy/cacheKey";

function makeWorkspace(seed: string): string {
  const root = mkdtempSync(join(tmpdir(), `waygent-cache-key-${seed}-`));
  writeFileSync(join(root, "bun.lock"), "# bun lockfile v0\nfoo@1.0.0\n");
  writeFileSync(
    join(root, "package.json"),
    JSON.stringify({
      name: "root",
      private: true,
      workspaces: ["packages/*"],
      dependencies: { left: "1.0.0" }
    })
  );
  mkdirSync(join(root, "packages", "alpha"), { recursive: true });
  writeFileSync(
    join(root, "packages", "alpha", "package.json"),
    JSON.stringify({ name: "@waygent-test/alpha", version: "0.0.1" })
  );
  mkdirSync(join(root, "packages", "beta"), { recursive: true });
  writeFileSync(
    join(root, "packages", "beta", "package.json"),
    JSON.stringify({ name: "@waygent-test/beta", version: "0.0.1" })
  );
  return root;
}

describe("computeCacheKey", () => {
  test("returns a sha256-prefixed hex key with stable shape", () => {
    const workspace = makeWorkspace("shape");
    const result = computeCacheKey({ workspace });
    expect(result.key).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(result.components.map((c) => c.path)).toEqual([
      "bun.lock",
      "packages/alpha/package.json",
      "packages/beta/package.json",
      "package.json#canonical"
    ]);
  });

  test("is stable across repeated computations on the same inputs", () => {
    const workspace = makeWorkspace("stable");
    const a = computeCacheKey({ workspace });
    const b = computeCacheKey({ workspace });
    expect(a.key).toBe(b.key);
  });

  test("produces a new key when bun.lock changes", () => {
    const workspace = makeWorkspace("lockfile");
    const before = computeCacheKey({ workspace }).key;
    writeFileSync(join(workspace, "bun.lock"), "# bun lockfile v0\nfoo@2.0.0\n");
    const after = computeCacheKey({ workspace }).key;
    expect(after).not.toBe(before);
  });

  test("produces a new key when a new packages/* manifest is added", () => {
    const workspace = makeWorkspace("add-pkg");
    const before = computeCacheKey({ workspace }).key;
    mkdirSync(join(workspace, "packages", "gamma"), { recursive: true });
    writeFileSync(
      join(workspace, "packages", "gamma", "package.json"),
      JSON.stringify({ name: "@waygent-test/gamma", version: "0.0.1" })
    );
    const after = computeCacheKey({ workspace }).key;
    expect(after).not.toBe(before);
  });

  test("produces a new key when an existing packages/* manifest changes", () => {
    const workspace = makeWorkspace("change-pkg");
    const before = computeCacheKey({ workspace }).key;
    writeFileSync(
      join(workspace, "packages", "alpha", "package.json"),
      JSON.stringify({ name: "@waygent-test/alpha", version: "0.0.2" })
    );
    const after = computeCacheKey({ workspace }).key;
    expect(after).not.toBe(before);
  });

  test("changes when root package.json workspaces field changes", () => {
    const workspace = makeWorkspace("root-workspaces");
    const before = computeCacheKey({ workspace }).key;
    writeFileSync(
      join(workspace, "package.json"),
      JSON.stringify({
        name: "root",
        private: true,
        workspaces: ["packages/*", "apps/*"],
        dependencies: { left: "1.0.0" }
      })
    );
    const after = computeCacheKey({ workspace }).key;
    expect(after).not.toBe(before);
  });

  test("changes when root package.json dependencies change", () => {
    const workspace = makeWorkspace("root-deps");
    const before = computeCacheKey({ workspace }).key;
    writeFileSync(
      join(workspace, "package.json"),
      JSON.stringify({
        name: "root",
        private: true,
        workspaces: ["packages/*"],
        dependencies: { left: "2.0.0" }
      })
    );
    const after = computeCacheKey({ workspace }).key;
    expect(after).not.toBe(before);
  });

  test("ignores unrelated root package.json fields (e.g. name, scripts)", () => {
    const workspace = makeWorkspace("root-unrelated");
    const before = computeCacheKey({ workspace }).key;
    writeFileSync(
      join(workspace, "package.json"),
      JSON.stringify({
        name: "renamed-root",
        private: false,
        scripts: { check: "echo new" },
        workspaces: ["packages/*"],
        dependencies: { left: "1.0.0" }
      })
    );
    const after = computeCacheKey({ workspace }).key;
    expect(after).toBe(before);
  });

  test("is insensitive to root package.json key ordering", () => {
    const workspace = makeWorkspace("root-order");
    const before = computeCacheKey({ workspace }).key;
    writeFileSync(
      join(workspace, "package.json"),
      JSON.stringify({
        dependencies: { left: "1.0.0" },
        workspaces: ["packages/*"],
        name: "root",
        private: true
      })
    );
    const after = computeCacheKey({ workspace }).key;
    expect(after).toBe(before);
  });
});
