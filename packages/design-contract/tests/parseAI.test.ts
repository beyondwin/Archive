import { describe, expect, it } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  FakeExtractorProvider,
  extractDesignWithAI,
  type ExtractorResponse
} from "../src/parse/ai";

const fixDir = join(import.meta.dir, "fixtures/freeform");

function loadResp(name: string): ExtractorResponse {
  return JSON.parse(readFileSync(join(fixDir, `${name}.ai-response.json`), "utf8"));
}

describe("extractDesignWithAI", () => {
  it("returns ok with validated payload from fake provider", async () => {
    const md = readFileSync(join(fixDir, "design-korean-prose.md"), "utf8");
    const provider = new FakeExtractorProvider(
      new Map([["design:design-korean-prose.md", loadResp("design-korean-prose")]])
    );
    const out = await extractDesignWithAI(provider, md, "design-korean-prose.md");
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.parser).toBe("ai");
    const first = out.value.invariants[0] as { id: string };
    expect(first.id).toBe("INV-001");
    expect(out.log.reasoning).toContain("two file paths");
  });

  it("retries once on malformed payload then fails", async () => {
    const provider = new FakeExtractorProvider(new Map([["design:bad.md", "malformed"]]));
    const out = await extractDesignWithAI(provider, "# x", "bad.md");
    expect(out.kind).toBe("failed");
  });

  it("retries twice on transient throw then fails", async () => {
    const provider = new FakeExtractorProvider(new Map([["design:bad.md", "throw"]]));
    const out = await extractDesignWithAI(provider, "# x", "bad.md");
    expect(out.kind).toBe("failed");
    if (out.kind !== "failed") return;
    expect(out.reason).toContain("ai_provider_error");
  });
});
