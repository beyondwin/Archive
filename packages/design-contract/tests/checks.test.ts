import { describe, expect, it } from "bun:test";
import { runInvariantCheck } from "../src/checks";

describe("runInvariantCheck", () => {
  it("shell: passes when command exits 0", async () => {
    const res = await runInvariantCheck(
      { kind: "shell", command: "true", expect_exit_zero: true },
      process.cwd()
    );
    expect(res.passed).toBe(true);
  });

  it("shell: fails when command exits non-zero", async () => {
    const res = await runInvariantCheck(
      { kind: "shell", command: "false", expect_exit_zero: true },
      process.cwd()
    );
    expect(res.passed).toBe(false);
    expect(res.evidence).toContain("exit");
  });

  it("file_exists: passes for present file", async () => {
    const res = await runInvariantCheck({ kind: "file_exists", path: "package.json" }, process.cwd());
    expect(res.passed).toBe(true);
  });

  it("file_exists: fails for missing file", async () => {
    const res = await runInvariantCheck(
      { kind: "file_exists", path: "definitely-not-here.xyz" },
      process.cwd()
    );
    expect(res.passed).toBe(false);
  });
});
