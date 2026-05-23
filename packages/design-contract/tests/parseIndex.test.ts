import { describe, expect, it } from "bun:test";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { FakeExtractorProvider, type ExtractorResponse } from "../src/parse/ai";
import { parseDesignSource } from "../src/parse";

const fixCanonical = join(import.meta.dir, "fixtures/canonical");
const fixFreeform = join(import.meta.dir, "fixtures/freeform");

function loadResp(name: string): ExtractorResponse {
  return JSON.parse(readFileSync(join(fixFreeform, `${name}.ai-response.json`), "utf8"));
}

describe("parseDesignSource fallback chain", () => {
  it("uses deterministic when canonical input parses", async () => {
    const md = readFileSync(join(fixCanonical, "design-simple.md"), "utf8");
    const cacheRoot = mkdtempSync(join(tmpdir(), "dc-cache-"));
    const provider = new FakeExtractorProvider(new Map());
    const out = await parseDesignSource(md, "design-simple.md", { cacheRoot, provider });
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.parser).toBe("deterministic");
  });

  it("falls back to AI when deterministic returns incomplete", async () => {
    const md = readFileSync(join(fixFreeform, "design-korean-prose.md"), "utf8");
    const cacheRoot = mkdtempSync(join(tmpdir(), "dc-cache-"));
    const provider = new FakeExtractorProvider(
      new Map([["design:design-korean-prose.md", loadResp("design-korean-prose")]])
    );
    const out = await parseDesignSource(md, "design-korean-prose.md", { cacheRoot, provider });
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.parser).toBe("ai");
  });

  it("returns cached on second call with same source", async () => {
    const md = readFileSync(join(fixFreeform, "design-korean-prose.md"), "utf8");
    const cacheRoot = mkdtempSync(join(tmpdir(), "dc-cache-"));
    const provider = new FakeExtractorProvider(
      new Map([["design:design-korean-prose.md", loadResp("design-korean-prose")]])
    );
    const first = await parseDesignSource(md, "design-korean-prose.md", { cacheRoot, provider });
    expect(first.kind).toBe("ok");
    const second = await parseDesignSource(md, "design-korean-prose.md", { cacheRoot, provider });
    expect(second.kind).toBe("ok");
    if (second.kind !== "ok") return;
    expect(second.value.parser).toBe("cached");
  });

  it("returns failed when both deterministic and AI fail", async () => {
    const md = "# nothing\n";
    const cacheRoot = mkdtempSync(join(tmpdir(), "dc-cache-"));
    const provider = new FakeExtractorProvider(new Map([["design:nothing.md", "throw"]]));
    const out = await parseDesignSource(md, "nothing.md", { cacheRoot, provider });
    expect(out.kind).toBe("failed");
  });
});
