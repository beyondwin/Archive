import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { normalizeProcessOutput } from "../src";

const fixtureDir = join(import.meta.dir, "fixtures");

function readFixture(name: string): string {
  return readFileSync(join(fixtureDir, name), "utf8");
}

describe("parseWorkerOutput hardening", () => {
  test("extracts a fenced json worker_result from a claude narrative envelope (D-09 regression)", () => {
    const stdout = readFixture("claude_task_3_narrative_then_json.stdout.txt");
    const result = normalizeProcessOutput("claude", "task_3_fixture_preparation_and_gradle_injection", "candidate_task_3", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false,
      startedAt: "2026-05-22T20:00:00.000Z",
      completedAt: "2026-05-22T20:30:50.000Z"
    });
    expect(result.worker.status).toBe("completed");
    expect(result.worker.failure_class).toBeUndefined();
    expect(result.worker.changed_files).toContain("scripts/source-matching-fixtures.mjs");
    expect(result.worker.changed_files).toContain("app/build.gradle.kts");
    expect(result.worker.changed_files).toContain("app/src/test/resources/baseline.json");
    expect(result.worker.summary).toContain("npm run source-matching:fixtures:test");
  });

  test("prefers the json-labeled fence over a bash fence appearing earlier in the document", () => {
    const stdout = [
      "Here is the script:",
      "```bash",
      "echo hello { world }",
      "```",
      "",
      "And the result:",
      "```json",
      JSON.stringify({
        schema: "runway.worker_result.v1",
        task_id: "task_demo",
        candidate_id: "candidate_demo",
        status: "completed",
        changed_files: ["a.ts"],
        summary: "fence ordering test",
        evidence: {}
      }),
      "```"
    ].join("\n");
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.worker.status).toBe("completed");
    expect(result.worker.summary).toBe("fence ordering test");
    expect(result.worker.changed_files).toEqual(["a.ts"]);
  });

  test("recovers via balanced-brace fallback when no fence is present", () => {
    const stdout = [
      "Implementer narrative without code fences but with embedded JSON.",
      "Look at this brace-only chunk that doesn't belong: { just_a_note: 1 }",
      JSON.stringify({
        schema: "runway.worker_result.v1",
        task_id: "task_demo",
        candidate_id: "candidate_demo",
        status: "completed",
        changed_files: ["b.ts"],
        summary: "brace fallback test",
        evidence: {}
      }),
      "Trailing prose."
    ].join("\n");
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.worker.status).toBe("completed");
    expect(result.worker.summary).toBe("brace fallback test");
    expect(result.worker.changed_files).toEqual(["b.ts"]);
  });

  test("ignores braces that appear inside string literals when scanning balanced spans", () => {
    const stdout = [
      'Prose with a "fake { not real }" string and then:',
      JSON.stringify({
        schema: "runway.worker_result.v1",
        task_id: "task_demo",
        candidate_id: "candidate_demo",
        status: "completed",
        changed_files: ["c.ts"],
        summary: "string-aware scan",
        evidence: { note: "the worker should still be found" }
      })
    ].join("\n");
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.worker.status).toBe("completed");
    expect(result.worker.summary).toBe("string-aware scan");
    expect(result.worker.changed_files).toEqual(["c.ts"]);
  });

  test("still parses a minimal direct-JSON worker_result", () => {
    const stdout = readFixture("synthetic_minimal.stdout.txt");
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.worker.status).toBe("completed");
    expect(result.worker.changed_files).toEqual(["a.ts"]);
    expect(result.worker.summary).toBe("minimal");
  });

  test("classifies output with no worker_result anywhere as malformed_result", () => {
    const stdout = [
      "Just narrative without any JSON.",
      "```bash",
      "echo nothing useful",
      "```"
    ].join("\n");
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout,
      stderr: "no useful output",
      timedOut: false
    });
    expect(result.worker.status).toBe("failed");
    expect(result.worker.failure_class).toBe("malformed_result");
  });

  test("preserves a worker_result fenced inside a claude `result` envelope string", () => {
    const stdout = JSON.stringify({
      type: "result",
      result: [
        "Here is some prose first.",
        "",
        "```yaml",
        "fixtures: [a, b]",
        "```",
        "",
        "```json",
        JSON.stringify({
          schema: "runway.worker_result.v1",
          task_id: "task_demo",
          candidate_id: "candidate_demo",
          status: "completed",
          changed_files: ["d.ts"],
          summary: "envelope unwrap",
          evidence: {}
        }),
        "```"
      ].join("\n")
    });
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.worker.status).toBe("completed");
    expect(result.worker.summary).toBe("envelope unwrap");
    expect(result.worker.changed_files).toEqual(["d.ts"]);
  });

  test.each([
    ["complete", "completed"],
    ["implemented", "completed"],
    ["success", "completed"],
    ["succeeded", "completed"],
    ["done", "completed"],
    ["ok", "completed"],
    ["ready", "completed"],
    ["ready_for_review", "completed"],
    ["ready-for-review", "completed"],
    ["Ready_For_Review", "completed"],
    ["COMPLETE", "completed"],
    [" Implemented ", "completed"],
    ["error", "failed"],
    ["errored", "failed"],
    ["failure", "failed"],
    ["halted", "blocked"],
    ["stopped", "blocked"],
    ["paused", "blocked"]
  ])("accepts %p as worker status synonym and normalizes to %p", (raw, expected) => {
    const stdout = JSON.stringify({
      type: "result",
      result: JSON.stringify({
        schema: "runway.worker_result.v1",
        task_id: "task_demo",
        candidate_id: "candidate_demo",
        status: raw,
        changed_files: ["f.ts"],
        summary: "synonym status accepted",
        evidence: {}
      })
    });
    const result = normalizeProcessOutput("claude", "task_demo", "candidate_demo", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.worker.status).toBe(expected as "completed" | "failed" | "blocked");
    expect(result.worker.failure_class).toBeUndefined();
  });
});
