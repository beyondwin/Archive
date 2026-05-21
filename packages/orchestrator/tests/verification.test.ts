import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runVerificationCommands } from "../src/verification";

describe("Waygent verification", () => {
  test("runs commands and records failure without trusting provider claims", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "waygent-verify-"));
    writeFileSync(join(cwd, "README.md"), "hello\n");

    const result = await runVerificationCommands({
      run_id: "run_verify",
      task_id: "task_verify",
      cwd,
      commands: ["test -f README.md", "test -f missing.txt"]
    });

    expect(result.status).toBe("failed");
    expect(result.results).toHaveLength(2);
    expect(result.results[1]?.exit_code).not.toBe(0);
  });
});
