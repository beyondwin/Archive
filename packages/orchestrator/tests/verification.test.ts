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

  test("classifies missing package verification output as dependency_missing", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "waygent-verify-"));
    const result = await runVerificationCommands({
      run_id: "run_verify",
      task_id: "task_verify",
      cwd,
      commands: ["node -e \"throw new Error('Cannot find package ajv from validate.ts')\""]
    });

    expect(result.status).toBe("failed");
    expect(result.failure_class).toBe("dependency_missing");
    expect(result.failure_summary).toContain("Cannot find package");
  });

  test("classifies missing command verification output as command_not_found", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "waygent-verify-"));
    const result = await runVerificationCommands({
      run_id: "run_verify",
      task_id: "task_verify",
      cwd,
      commands: ["definitely-not-a-waygent-command"]
    });

    expect(result.status).toBe("failed");
    expect(result.failure_class).toBe("command_not_found");
  });

  test("classifies timed out verification output as timeout", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "waygent-verify-"));
    const result = await runVerificationCommands({
      run_id: "run_verify",
      task_id: "task_verify",
      cwd,
      commands: ["sleep 1"],
      timeout_ms: 10
    });

    expect(result.status).toBe("failed");
    expect(result.failure_class).toBe("timeout");
  });
});
