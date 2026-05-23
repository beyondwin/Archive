import { describe, expect, it, beforeEach } from "bun:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ArtifactCache } from "../src/parse/cache";

let root: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "design-contract-cache-"));
});

describe("ArtifactCache", () => {
  it("returns null on miss, hit on store + read", async () => {
    const cache = new ArtifactCache(root);
    const key = { sourcePath: "x.md", sourceSha256: "abc", extractorVersion: "v1" };
    expect(await cache.read(key)).toBeNull();
    await cache.write(key, { hello: "world" });
    expect(await cache.read(key)).toEqual({ hello: "world" });
  });

  it("invalidates when key hash differs", async () => {
    const cache = new ArtifactCache(root);
    await cache.write(
      { sourcePath: "x.md", sourceSha256: "a", extractorVersion: "v1" },
      { v: 1 }
    );
    expect(
      await cache.read({ sourcePath: "x.md", sourceSha256: "b", extractorVersion: "v1" })
    ).toBeNull();
  });

  it("returns null when stored payload is malformed JSON", async () => {
    const cache = new ArtifactCache(root);
    const key = { sourcePath: "x.md", sourceSha256: "abc", extractorVersion: "v1" };
    await cache.write(key, { ok: true });
    await Bun.write(cache.pathFor(key), "not-json{");
    expect(await cache.read(key)).toBeNull();
  });
});
