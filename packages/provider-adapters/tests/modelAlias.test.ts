import { describe, expect, test } from "bun:test";
import { canonicalModelFamily, isFamilyAlias, modelsMatch } from "../src/modelAlias";

describe("canonicalModelFamily", () => {
  test.each([
    ["opus", "opus"],
    ["Opus", "opus"],
    ["claude-opus-4-7", "opus"],
    ["claude-opus-4-6", "opus"],
    ["sonnet", "sonnet"],
    ["claude-sonnet-4-6", "sonnet"],
    ["haiku", "haiku"],
    ["claude-haiku-4-5", "haiku"],
    ["claude-haiku-4-5-20251001", "haiku"],
    ["gpt-5.5", "gpt-5"],
    ["gpt-5", "gpt-5"],
    ["gpt5.5", "gpt-5"],
    ["GPT-5.5-2026-01-01", "gpt-5"]
  ])("maps %p to family %p", (raw, family) => {
    expect(canonicalModelFamily(raw)).toBe(family);
  });

  test.each([
    [null],
    [undefined],
    [""],
    ["   "],
    ["fake"],
    ["custom-model"]
  ])("returns null for %p", (raw) => {
    expect(canonicalModelFamily(raw as string | null | undefined)).toBeNull();
  });
});

describe("isFamilyAlias", () => {
  test.each([
    ["opus", true],
    ["OPUS", true],
    ["sonnet", true],
    ["haiku", true],
    ["gpt-5", true],
    ["gpt5", true],
    ["gpt-5.5", true],
    ["gpt5.5", true],
    ["claude-opus-4-7", false],
    ["claude-sonnet-4-6", false],
    ["gpt-5.5-2026-01-01", false],
    ["", false],
    ["custom", false]
  ])("isFamilyAlias(%p) === %p", (raw, expected) => {
    expect(isFamilyAlias(raw)).toBe(expected);
  });
});

describe("modelsMatch", () => {
  test("exact string match", () => {
    expect(modelsMatch("claude-opus-4-7", "claude-opus-4-7")).toBe(true);
    expect(modelsMatch("opus", "opus")).toBe(true);
  });

  test("family alias requested matches resolved build", () => {
    expect(modelsMatch("opus", "claude-opus-4-7")).toBe(true);
    expect(modelsMatch("sonnet", "claude-sonnet-4-6")).toBe(true);
    expect(modelsMatch("haiku", "claude-haiku-4-5-20251001")).toBe(true);
    expect(modelsMatch("gpt-5.5", "gpt-5.5-2026-01-01")).toBe(true);
  });

  test("pinned build vs different build in same family is a mismatch", () => {
    expect(modelsMatch("claude-opus-4-7", "claude-opus-4-6")).toBe(false);
  });

  test("cross-family is always a mismatch", () => {
    expect(modelsMatch("opus", "claude-sonnet-4-6")).toBe(false);
    expect(modelsMatch("opus", "gpt-5.5")).toBe(false);
  });

  test("nullish inputs are mismatches", () => {
    expect(modelsMatch(null, "opus")).toBe(false);
    expect(modelsMatch("opus", null)).toBe(false);
    expect(modelsMatch(undefined, undefined)).toBe(false);
    expect(modelsMatch("", "opus")).toBe(false);
  });

  test("unknown family falls back to exact equality only", () => {
    expect(modelsMatch("custom-model", "custom-model")).toBe(true);
    expect(modelsMatch("custom-model", "custom-model-v2")).toBe(false);
  });
});
