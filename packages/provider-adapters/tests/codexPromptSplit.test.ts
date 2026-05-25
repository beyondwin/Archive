import { describe, expect, test } from "bun:test";
import { buildProviderStdinPrompt, buildProviderSystemPrompt, buildProviderUserPrompt } from "../src/processAdapters";

describe("codex sentinel prompt split (C2)", () => {
  test("Codex stdin wraps system + user content in sentinel tags", () => {
    const stdin = buildProviderStdinPrompt("codex", {
      task_id: "task_a",
      candidate_id: "candidate_task_a",
      role: "implement",
      prompt: "Implement feature X",
      task_packet_path: "/tmp/packet.json"
    });
    expect(stdin).toContain('<system_instructions role="implement">');
    expect(stdin).toContain("</system_instructions>");
    expect(stdin).toContain("<user_request>");
    expect(stdin).toContain("</user_request>");
    expect(stdin).toContain(buildProviderSystemPrompt("implement"));
    expect(stdin).toContain("task_id: task_a");
    expect(stdin).toContain("Task prompt:");
  });

  test("system_instructions prefix is byte-stable per role across requests (cache amortization)", () => {
    const prefix = (request: Parameters<typeof buildProviderStdinPrompt>[1]) =>
      buildProviderStdinPrompt("codex", request).split("</system_instructions>")[0]!;
    const a = prefix({ task_id: "task_a", candidate_id: "c_a", role: "implement", prompt: "do A" });
    const b = prefix({ task_id: "task_b", candidate_id: "c_b", role: "implement", prompt: "do B" });
    expect(a).toBe(b);
  });

  test("review role yields a different system_instructions prefix than implement", () => {
    const implement = buildProviderStdinPrompt("codex", { task_id: "t", candidate_id: "c", role: "implement", prompt: "x" });
    const review = buildProviderStdinPrompt("codex", { task_id: "t", candidate_id: "c", role: "review", prompt: "x" });
    expect(implement.split("</system_instructions>")[0])
      .not.toBe(review.split("</system_instructions>")[0]);
    expect(review).toContain('<system_instructions role="review">');
  });

  test("Claude stdin remains the user-prompt only (no sentinel wrapping)", () => {
    const stdin = buildProviderStdinPrompt("claude", {
      task_id: "t",
      candidate_id: "c",
      role: "implement",
      prompt: "go"
    });
    expect(stdin).toBe(buildProviderUserPrompt("claude", {
      task_id: "t",
      candidate_id: "c",
      role: "implement",
      prompt: "go"
    }));
    expect(stdin).not.toContain("<system_instructions");
  });

  test("Codex retry prefix is carried inside <user_request> via buildProviderUserPrompt", () => {
    const stdin = buildProviderStdinPrompt("codex", {
      task_id: "t",
      candidate_id: "c",
      role: "implement",
      prompt: "go",
      retry_context: { failure_class: "verification_failed", stderr_summary: "compile error" }
    });
    expect(stdin).toContain("Prior attempt failed: verification_failed");
    // Retry prefix should live inside <user_request>, not before the system block.
    const userStart = stdin.indexOf("<user_request>");
    const retryIdx = stdin.indexOf("Prior attempt failed");
    expect(retryIdx).toBeGreaterThan(userStart);
  });
});
