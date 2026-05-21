import { mkdtempSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import { buildRepoMap } from "../src";

describe("Graphify-free repo map", () => {
  test("discovers files without reading graphify-out", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-map-"));
    writeFileSync(join(root, "a.ts"), "export const a = 1;");
    const map = buildRepoMap(root);
    expect(map[0]?.path).toBe("a.ts");
  });
});
