import { describe, expect, test } from "bun:test";
import { evaluatePolicy, permissionProfile } from "../src";

describe("policy rule engine", () => {
  test("explains command denials", () => {
    const result = evaluatePolicy({
      mode: "execute",
      command: ["rm", "-rf", "x"],
      cwd: ".",
      writes: [],
      profile: permissionProfile({ command_prefixes: ["bun"] })
    });
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("rm");
  });
});
