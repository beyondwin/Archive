import { describe, expect, test } from "bun:test";
import { applyCodexResumeContext, resolveExecutionProfile, resolveProviderProcesses } from "../src";

describe("codex resume context injection (C3 orchestrator)", () => {
  test("applyCodexResumeContext adds resume_session_id only when codex process is present", () => {
    const profile = resolveExecutionProfile({ provider: "codex" });
    const base = resolveProviderProcesses(profile, undefined);
    const next = applyCodexResumeContext(base, "thread_abc");
    expect(next.codex?.resume_session_id).toBe("thread_abc");
  });

  test("applyCodexResumeContext is a no-op when no resume session captured yet", () => {
    const profile = resolveExecutionProfile({ provider: "codex" });
    const base = resolveProviderProcesses(profile, undefined);
    const next = applyCodexResumeContext(base, undefined);
    expect(next).toBe(base);
    expect(next.codex?.resume_session_id).toBeUndefined();
  });

  test("applyCodexResumeContext preserves an explicit resume_session_id override", () => {
    const profile = resolveExecutionProfile({ provider: "codex" });
    const base = resolveProviderProcesses(profile, {
      codex: { executable: "codex", args: ["exec", "--json", "-"], resume_session_id: "user-pinned" }
    });
    const next = applyCodexResumeContext(base, "auto-captured");
    expect(next.codex?.resume_session_id).toBe("user-pinned");
  });

  test("applyCodexResumeContext is a no-op for Claude-only configurations", () => {
    const profile = resolveExecutionProfile({ provider: "claude" });
    const base = resolveProviderProcesses(profile, undefined);
    const next = applyCodexResumeContext(base, "thread_abc");
    expect(next.codex).toBeUndefined();
  });
});
