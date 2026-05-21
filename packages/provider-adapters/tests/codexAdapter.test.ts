import { describe, expect, test } from "bun:test";
import { normalizeProcessOutput } from "../src";

describe("Codex adapter normalization", () => {
  test("normalizes fake CLI output", () => {
    const result = normalizeProcessOutput("codex", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout: JSON.stringify({ summary: "done", changed_files: ["a.ts"], evidence: { command: "codex" } }),
      stderr: ""
    });
    expect(result.changed_files).toEqual(["a.ts"]);
  });

  test("classifies crashes", () => {
    expect(normalizeProcessOutput("codex", "task_demo", "candidate_demo", { exitCode: 2, stdout: "", stderr: "boom" }).failure_class).toBe(
      "adapter_crashed"
    );
  });
});
