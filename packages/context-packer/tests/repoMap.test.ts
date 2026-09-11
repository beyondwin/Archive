import { mkdtempSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import { buildRepoMap } from "../src";

describe("repository map", () => {
  test("discovers source files", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-map-"));
    writeFileSync(join(root, "a.ts"), "export const a = 1;");
    const map = buildRepoMap(root);
    expect(map[0]?.path).toBe("a.ts");
  });

  test("discovers source files when ripgrep is missing", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-map-norg-"));
    writeFileSync(join(root, "a.ts"), "export const a = 1;");
    const previousPath = process.env.PATH;
    process.env.PATH = "";
    try {
      const map = buildRepoMap(root);
      expect(map[0]?.path).toBe("a.ts");
    } finally {
      process.env.PATH = previousPath;
    }
  });
});
