import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { validatePlanChainInputs } from "../src/planChain";

describe("plan chain", () => {
  test("rejects mismatched repeatable plan/spec counts before execution", () => {
    expect(() => validatePlanChainInputs({ plans: ["a.md", "b.md"], specs: ["a-spec.md"] })).toThrow(/mismatched plan\/spec/);
  });

  test("allows omitted specs for every plan", () => {
    expect(validatePlanChainInputs({ plans: ["a.md", "b.md"], specs: [] })).toEqual([
      { plan: "a.md", spec: null, index: 1 },
      { plan: "b.md", spec: null, index: 2 }
    ]);
  });
});
