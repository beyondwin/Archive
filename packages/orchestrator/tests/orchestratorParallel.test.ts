import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readEvents } from "@waygent/lens-store";
import { runWaygent } from "../src/orchestrator";
import { readRunStateV2 } from "../src/runState";
import { initSourceCheckout } from "./support/orchestratorFixtures";

describe("Waygent safe-wave parallel execution", () => {
  test("executes independent low-risk tasks in one bounded parallel wave", async () => {
    const workspace = initSourceCheckout("waygent-parallel-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-parallel-root-"));

    await runWaygent({
      root,
      workspace,
      run_id: "run_parallel",
      plan: independentPlan(4),
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_parallel");
    const events = readEvents(join(root, "run_parallel", "events.jsonl"));
    const firstWave = state.safe_waves[0] as Record<string, unknown>;

    expect(state.safe_waves[0]?.ready).toEqual(["task_1", "task_2", "task_3", "task_4"]);
    expect(Object.values(state.tasks).every((task) => task.status === "verified")).toBe(true);
    expect(state.provider_attempts).toHaveLength(4);
    expect(new Set(events.map((event) => event.sequence)).size).toBe(events.length);
    expect(firstWave.concurrency).toBe(4);
    expect(firstWave.timing).toMatchObject({ duration_ms: expect.any(Number) });
    expect(state.completion_audit).toMatchObject({ status: "passed" });
  });

  test("keeps conflicting claims serialized by the scheduler", async () => {
    const workspace = initSourceCheckout("waygent-serial-claim-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-serial-claim-root-"));

    await runWaygent({
      root,
      workspace,
      run_id: "run_serial_claim",
      plan: conflictingPlan(),
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_serial_claim");
    expect(state.safe_waves[0]?.ready).toEqual(["task_first"]);
    expect(state.safe_waves[1]?.ready).toEqual(["task_second"]);
    expect(readFileSync(join(workspace, "README.md"), "utf8")).toBe("fixture\n");
  });

  test("records task executor crashes without losing successful sibling evidence", async () => {
    const workspace = initSourceCheckout("waygent-wave-crash-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-wave-crash-root-"));

    await runWaygent({
      root,
      workspace,
      run_id: "run_wave_crash",
      plan: [
        "```yaml waygent-task",
        "id: task_ok",
        "title: Create ok file",
        "dependencies: []",
        "file_claims:",
        "  - path: ok.txt",
        "    mode: owned",
        "risk: low",
        "verify:",
        "  - test -f ok.txt",
        "```",
        "```yaml waygent-task",
        "id: task_crash",
        "title: Crash during materialization",
        "dependencies: []",
        "file_claims:",
        `  - path: bad${"\0"}path.txt`,
        "    mode: owned",
        "risk: low",
        "verify:",
        `  - test -f bad${"\0"}path.txt`,
        "```"
      ].join("\n"),
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_wave_crash");
    const events = readEvents(join(root, "run_wave_crash", "events.jsonl"));

    expect(state.tasks.task_ok).toMatchObject({
      status: "verified",
      checkpoint_refs: [expect.stringContaining("artifacts/checkpoints/task_ok/")]
    });
    expect(state.tasks.task_crash).toMatchObject({
      status: "blocked",
      latest_failure_class: "adapter_crashed"
    });
    expect(state.provider_attempts.map((attempt) => attempt.task_id)).toContain("task_ok");
    expect(events.find((event) => event.payload.task_id === "task_crash")).toMatchObject({
      outcome: "failed",
      payload: { failure_class: "adapter_crashed" }
    });
    expect(state.completion_audit).toMatchObject({ status: "failed" });
  });

  test("preserves sibling evidence when a process provider crashes in the same safe wave", async () => {
    const workspace = initSourceCheckout("waygent-process-crash-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-process-crash-root-"));
    const script = `
      import { writeFileSync } from "node:fs";
      const prompt = await new Response(Bun.stdin.stream()).text();
      if (prompt.includes("task_provider_crash")) {
        console.error("provider crashed intentionally");
        process.exit(2);
      }
      writeFileSync("provider-ok.txt", "ok\\n");
      console.log(JSON.stringify({
        schema: "runway.worker_result.v1",
        task_id: "task_provider_ok",
        candidate_id: "candidate_task_provider_ok",
        status: "completed",
        changed_files: ["provider-ok.txt"],
        summary: "provider ok",
        evidence: { fixture: "process-crash" }
      }));
    `;

    await runWaygent({
      root,
      workspace,
      run_id: "run_process_crash",
      plan: [
        "```yaml waygent-task",
        "id: task_provider_ok",
        "title: Process provider succeeds",
        "dependencies: []",
        "file_claims:",
        "  - path: provider-ok.txt",
        "    mode: owned",
        "risk: low",
        "verify:",
        "  - test -f provider-ok.txt",
        "```",
        "```yaml waygent-task",
        "id: task_provider_crash",
        "title: Process provider crashes",
        "dependencies: []",
        "file_claims:",
        "  - path: provider-crash.txt",
        "    mode: owned",
        "risk: low",
        "verify:",
        "  - printf crash",
        "```"
      ].join("\n"),
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: { codex: { executable: process.execPath, args: ["-e", script] } }
    });

    const state = readRunStateV2(root, "run_process_crash");
    const events = readEvents(join(root, "run_process_crash", "events.jsonl"));

    expect(state.tasks.task_provider_ok).toMatchObject({
      status: "verified",
      checkpoint_refs: [expect.stringContaining("artifacts/checkpoints/task_provider_ok/")]
    });
    expect(state.tasks.task_provider_crash).toMatchObject({
      status: "blocked",
      latest_failure_class: "adapter_crashed"
    });
    expect(state.provider_attempts.find((attempt) => attempt.task_id === "task_provider_crash")).toMatchObject({
      exit_code: 2,
      failure_class: "adapter_crashed"
    });
    expect(events.find((event) => event.payload.task_id === "task_provider_crash")).toMatchObject({
      outcome: "failed"
    });
    expect(state.completion_audit).toMatchObject({ status: "failed" });
  });
});

function independentPlan(count: number): string {
  return Array.from({ length: count }, (_, index) => {
    const id = `task_${index + 1}`;
    const path = `file-${index + 1}.txt`;
    return [
      "```yaml waygent-task",
      `id: ${id}`,
      `title: Create ${path}`,
      "dependencies: []",
      "file_claims:",
      `  - path: ${path}`,
      "    mode: owned",
      "risk: low",
      "verify:",
      `  - test -f ${path}`,
      "```"
    ].join("\n");
  }).join("\n");
}

function conflictingPlan(): string {
  return [
    "```yaml waygent-task",
    "id: task_first",
    "title: First README update",
    "dependencies: []",
    "file_claims:",
    "  - path: README.md",
    "    mode: owned",
    "risk: low",
    "verify:",
    "  - test -f README.md",
    "```",
    "```yaml waygent-task",
    "id: task_second",
    "title: Second README update",
    "dependencies: []",
    "file_claims:",
    "  - path: README.md",
    "    mode: owned",
    "risk: low",
    "verify:",
    "  - test -f README.md",
    "```"
  ].join("\n");
}
