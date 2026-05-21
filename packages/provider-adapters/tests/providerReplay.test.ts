import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { normalizeProcessOutput } from "../src";

const fixtures = join(import.meta.dir, "fixtures");

describe("provider contract replay fixtures", () => {
  test("replays Codex JSONL agent-message output", () => {
    const stdout = readFileSync(join(fixtures, "codex-jsonl-agent-message.jsonl"), "utf8");
    const result = normalizeProcessOutput("codex", "task_fixture", "candidate_fixture", {
      exitCode: 0,
      stdout,
      stderr: ""
    });

    expect(result.worker).toMatchObject({
      task_id: "task_fixture",
      candidate_id: "candidate_fixture",
      status: "completed",
      changed_files: ["fixture.txt"]
    });
    expect(result.process.stdout).toContain("turn.completed");
  });

  test("replays Claude fenced worker output", () => {
    const stdout = readFileSync(join(fixtures, "claude-fenced-result.txt"), "utf8");
    const result = normalizeProcessOutput("claude", "task_fixture", "candidate_fixture", {
      exitCode: 0,
      stdout,
      stderr: ""
    });

    expect(result.worker).toMatchObject({
      task_id: "task_fixture",
      candidate_id: "candidate_fixture",
      status: "completed",
      changed_files: ["fixture.txt"]
    });
  });
});
