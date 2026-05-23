import { describe, expect, it } from "bun:test";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { lintDesign } from "../src/lint";
import { FakeExtractorProvider } from "../src/parse/ai";

describe("lintDesign", () => {
  it("renders normalized invariants and 'no blockers' for canonical input", async () => {
    const md = readFileSync(
      join(import.meta.dir, "fixtures/canonical/design-simple.md"),
      "utf8"
    );
    const cacheRoot = mkdtempSync(join(tmpdir(), "lint-"));
    const provider = new FakeExtractorProvider(new Map());
    const out = await lintDesign(md, "design-simple.md", { cacheRoot, provider });
    expect(out.parser).toBe("deterministic");
    expect(out.report).toContain("INV-001");
    expect(out.report).toContain("invariants: 1");
  });

  it("reports failure when parse fails", async () => {
    const cacheRoot = mkdtempSync(join(tmpdir(), "lint-"));
    const provider = new FakeExtractorProvider(new Map([["design:x.md", "throw"]]));
    const out = await lintDesign("# empty\n", "x.md", { cacheRoot, provider });
    expect(out.report).toContain("FAILED");
  });
});
