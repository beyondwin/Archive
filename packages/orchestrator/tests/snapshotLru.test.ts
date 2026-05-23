import { describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, readdirSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { evictLru } from "../src/isolatedStrategy/snapshot";

function makeSnapshots(root: string, keys: string[]): void {
  let ts = Math.floor(Date.now() / 1000) - keys.length * 60;
  for (const key of keys) {
    const dir = join(root, key);
    mkdirSync(dir, { recursive: true });
    utimesSync(dir, ts, ts);
    ts += 60;
  }
}

describe("evictLru", () => {
  it("keeps newest N snapshots and removes the rest", () => {
    const root = mkdtempSync(join(tmpdir(), "sp2-lru-"));
    makeSnapshots(root, ["k1", "k2", "k3", "k4", "k5", "k6"]);
    evictLru(root, 3);
    const remaining = readdirSync(root).sort();
    expect(remaining).toEqual(["k4", "k5", "k6"]);
  });

  it("is a no-op when count <= keep", () => {
    const root = mkdtempSync(join(tmpdir(), "sp2-lru-"));
    makeSnapshots(root, ["k1", "k2"]);
    evictLru(root, 5);
    expect(readdirSync(root).sort()).toEqual(["k1", "k2"]);
  });

  it("handles missing root gracefully", () => {
    expect(() => evictLru(join(tmpdir(), "sp2-lru-missing"), 5)).not.toThrow();
  });
});
