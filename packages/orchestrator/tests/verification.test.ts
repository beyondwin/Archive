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

  test("passes explicit expected-failure verification when the command fails normally", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "waygent-verify-"));

    const result = await runVerificationCommands({
      run_id: "run_verify",
      task_id: "task_verify",
      cwd,
      commands: [{ command: "test -f missing.txt", expected_exit: "nonzero" }]
    });

    expect(result.status).toBe("passed");
    expect(result.results[0]?.exit_code).not.toBe(0);
  });

  test("does not treat infrastructure failures as expected RED verification", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "waygent-verify-"));

    const result = await runVerificationCommands({
      run_id: "run_verify",
      task_id: "task_verify",
      cwd,
      commands: [{ command: "definitely-not-a-waygent-command", expected_exit: "nonzero" }]
    });

    expect(result.status).toBe("failed");
    expect(result.failure_class).toBe("command_not_found");
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

  test("classifies pnpm non-tty install purge as environment_blocker", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "waygent-verify-"));
    const result = await runVerificationCommands({
      run_id: "run_verify",
      task_id: "task_verify",
      cwd,
      commands: [
        "printf 'Scope: all 4 workspace projects\\nERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY Aborted removal of modules directory due to no TTY\\n' && exit 1"
      ]
    });

    expect(result.status).toBe("failed");
    expect(result.failure_class).toBe("environment_blocker");
    expect(result.failure_summary).toContain("ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY");
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
