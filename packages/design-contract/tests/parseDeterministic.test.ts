import { describe, expect, it } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parseDesignDeterministic, parsePlanDeterministic } from "../src/parse/deterministic.ts";

const fixDir = join(import.meta.dir, "fixtures/canonical");

describe("parseDesignDeterministic", () => {
  it("parses canonical design markdown into expected JSON", () => {
    const md = readFileSync(join(fixDir, "design-simple.md"), "utf8");
    const expected = JSON.parse(readFileSync(join(fixDir, "design-simple.expected.json"), "utf8"));
    const out = parseDesignDeterministic(md, "design-simple.md");
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.invariants).toEqual(expected.invariants);
    expect(
      out.value.prescriptive_blocks.map((b: { id: string; language: string; body: string }) => ({
        id: b.id,
        language: b.language,
        body: b.body,
      })),
    ).toEqual(expected.prescriptive_blocks);
    expect(out.value.parser).toBe("deterministic");
  });

  it("returns incomplete when required heading missing", () => {
    const out = parseDesignDeterministic("# nothing here\n", "x.md");
    expect(out.kind).toBe("incomplete");
  });
});

describe("parsePlanDeterministic", () => {
  it("parses canonical plan markdown into expected JSON", () => {
    const md = readFileSync(join(fixDir, "plan-simple.md"), "utf8");
    const expected = JSON.parse(readFileSync(join(fixDir, "plan-simple.expected.json"), "utf8"));
    const out = parsePlanDeterministic(md, "plan-simple.md");
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.tasks).toEqual(expected.tasks);
  });
});
