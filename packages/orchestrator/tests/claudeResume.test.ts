import { describe, expect, test } from "bun:test";
import { providerProcessArgs } from "@waygent/provider-adapters";
import { deriveClaudeSessionId, injectClaudeSessionContext } from "../src/taskExecutor";
import { resolveProviderProcesses } from "../src/orchestrator";
import type { ExecutionProfile } from "../src/executionProfile";

const claudeProfile: ExecutionProfile = {
  provider: "claude",
  execution_mode: "multi-agent",
  main: { model: "claude-opus-4-7", reasoning: "high" },
  subagent: { model: "claude-sonnet-4-6", reasoning: "high" },
  evidence_event_type: "runway.execution_profile_selected"
};

const DERIVED_SESSION_ID = "456256f7-f40f-5e91-bb7a-c6373f2eaa73";

describe("Claude resume / session_id wiring", () => {
  test("deriveClaudeSessionId returns a deterministic UUIDv5 derived from run_id, task_id, candidate_id", () => {
    expect(
      deriveClaudeSessionId({ run_id: "run_1", task_id: "task_a", candidate_id: "candidate_task_a" })
    ).toBe(DERIVED_SESSION_ID);
  });

  test("injectClaudeSessionContext adds session_id when none configured", () => {
    const processes = injectClaudeSessionContext(
      { claude: { executable: "claude", args: ["-p"] } },
      { run_id: "run_1", task_id: "task_a", candidate_id: "candidate_task_a" }
    );
    expect(processes?.claude?.session_id).toBe(DERIVED_SESSION_ID);
  });

  test("injectClaudeSessionContext leaves existing session_id and resume_session_id intact", () => {
    const processes = injectClaudeSessionContext(
      { claude: { executable: "claude", args: ["-p"], session_id: "explicit", resume_session_id: "earlier" } },
      { run_id: "run_1", task_id: "task_a", candidate_id: "candidate_task_a" }
    );
    expect(processes?.claude?.session_id).toBe("explicit");
    expect(processes?.claude?.resume_session_id).toBe("earlier");
  });

  test("injectClaudeSessionContext is a no-op when claude provider is not configured", () => {
    const input = { codex: { executable: "codex", args: ["exec"] } };
    const processes = injectClaudeSessionContext(input, {
      run_id: "run_1",
      task_id: "task_a",
      candidate_id: "candidate_task_a"
    });
    expect(processes).toBe(input);
  });

  test("resolveProviderProcesses defaults Claude args to stream-json", () => {
    const resolved = resolveProviderProcesses(claudeProfile, undefined);
    expect(resolved.claude?.args).toEqual([
      "-p",
      "--output-format",
      "stream-json",
      "--include-partial-messages",
      "--verbose"
    ]);
  });

  test("resolveProviderProcesses preserves settings_path, mcp_config_path, timeout_ms_by_role overrides", () => {
    const resolved = resolveProviderProcesses(claudeProfile, {
      claude: {
        executable: "claude",
        args: ["-p"],
        settings_path: "/etc/settings.json",
        mcp_config_path: "/etc/mcp.json",
        timeout_ms_by_role: { review: 5 * 60 * 1000 }
      }
    });
    expect(resolved.claude?.settings_path).toBe("/etc/settings.json");
    expect(resolved.claude?.mcp_config_path).toBe("/etc/mcp.json");
    expect(resolved.claude?.timeout_ms_by_role).toEqual({ review: 5 * 60 * 1000 });
  });

  test("first-attempt args include --session-id and exclude --resume", () => {
    const args = providerProcessArgs(
      "claude",
      {
        executable: "claude",
        args: ["-p", "--output-format", "stream-json"],
        session_id: DERIVED_SESSION_ID
      },
      undefined,
      { task_id: "task_a", candidate_id: "candidate_task_a", role: "implement", prompt: "go" }
    );
    expect(args).toContain("--session-id");
    expect(args[args.indexOf("--session-id") + 1]).toBe(DERIVED_SESSION_ID);
    expect(args).not.toContain("--resume");
  });

  test("retry-attempt args include --resume and omit --session-id", () => {
    const args = providerProcessArgs(
      "claude",
      {
        executable: "claude",
        args: ["-p", "--output-format", "stream-json"],
        session_id: DERIVED_SESSION_ID,
        resume_session_id: DERIVED_SESSION_ID
      },
      undefined,
      { task_id: "task_a", candidate_id: "candidate_task_a", role: "implement", prompt: "go" }
    );
    expect(args).toContain("--resume");
    expect(args[args.indexOf("--resume") + 1]).toBe(DERIVED_SESSION_ID);
    expect(args).not.toContain("--session-id");
  });
});
