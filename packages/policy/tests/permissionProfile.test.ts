import { describe, expect, test } from "bun:test";
import { evaluatePolicy, permissionProfile } from "../src";

describe("permission profiles", () => {
  test("supports filesystem grants and denies", () => {
    const profile = permissionProfile({ filesystem: { read: ["."], write: ["packages"], deny: ["packages/secret"] } });
    expect(evaluatePolicy({ mode: "auto_edit", command: ["bun", "test"], cwd: ".", writes: ["packages/contracts/a.ts"], profile }).allowed).toBe(
      true
    );
    expect(evaluatePolicy({ mode: "auto_edit", command: ["bun", "test"], cwd: ".", writes: ["packages/secret/key"], profile }).denied_by).toBe(
      "filesystem.deny"
    );
  });
});
