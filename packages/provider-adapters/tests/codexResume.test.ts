import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { normalizeProcessOutput, providerProcessArgs } from "../src/processAdapters";

const fixturePath = join(import.meta.dir, "fixtures", "codex", "session_init.jsonl");

describe("codex retry resume (C3)", () => {
  test("first-attempt args use 'exec --json -' without 'resume' subcommand", () => {
    const args = providerProcessArgs(
      "codex",
      { executable: "codex", args: ["exec", "--json", "-"], model: "gpt-5.5", effort: "high" },
      undefined,
      { task_id: "t", candidate_id: "c", role: "implement", prompt: "go" }
    );
    expect(args).toContain("exec");
    expect(args).toContain("--json");
    expect(args).not.toContain("resume");
  });

  test("retry args insert 'resume <session_id>' after 'exec'", () => {
    const args = providerProcessArgs(
      "codex",
      {
        executable: "codex",
        args: ["exec", "--json", "-"],
        resume_session_id: "thread_codex_init_fixture",
        model: "gpt-5.5"
      },
      undefined,
      { task_id: "t", candidate_id: "c", role: "implement", prompt: "go" }
    );
    const execIdx = args.indexOf("exec");
    const resumeIdx = args.indexOf("resume");
    expect(resumeIdx).toBe(execIdx + 1);
    expect(args[resumeIdx + 1]).toBe("thread_codex_init_fixture");
    // The trailing stdin token "-" must still come after the resume + json flags.
    expect(args[args.length - 1]).toBe("-");
  });

  test("session_id is captured from the first stream-json envelope into evidence", () => {
    const stdout = readFileSync(fixturePath, "utf8");
    const result = normalizeProcessOutput("codex", "task_codex", "candidate_task_codex", {
      exitCode: 0,
      stdout,
      stderr: ""
    });
    expect(result.worker.evidence.session_id).toBe("thread_codex_init_fixture");
    expect(result.metadata?.session_id).toBe("thread_codex_init_fixture");
  });

  test("resume_session_missing is flagged when stderr matches the codex pattern", () => {
    const result = normalizeProcessOutput("codex", "task_codex", "candidate_task_codex", {
      exitCode: 0,
      stdout: '{"type":"thread.started","thread_id":"thread_x"}',
      stderr: "error: session was not found in store"
    });
    expect(result.worker.evidence.resume_session_missing).toBe(true);
    expect(result.metadata?.resume_session_missing).toBe(true);
  });

  test("resume_session_missing not flagged when stderr does not mention it", () => {
    const result = normalizeProcessOutput("codex", "task_codex", "candidate_task_codex", {
      exitCode: 0,
      stdout: '{"type":"thread.started","thread_id":"thread_x"}',
      stderr: "unrelated stderr"
    });
    expect(result.worker.evidence.resume_session_missing).toBeUndefined();
  });
});
