import { describe, expect, test } from "bun:test";
import { normalizeProcessOutput } from "../src";

describe("Claude adapter normalization", () => {
  test("classifies malformed output", () => {
    expect(normalizeProcessOutput("claude", "task_demo", "candidate_demo", { exitCode: 0, stdout: "not-json", stderr: "" }).failure_class).toBe(
      "malformed_result"
    );
  });
});
