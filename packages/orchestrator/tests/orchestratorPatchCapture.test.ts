import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import type { ProviderAttempt, WorkerResult } from "@waygent/contracts";
import { runWaygent, runWaygentDemo } from "../src";
import { initSourceCheckout } from "./support/orchestratorFixtures";

describe("orchestrator patch capture", () => {
  test("completed worker_result carries patch_ref + artifact exists on disk", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-patch-orch-"));
    const workspace = initSourceCheckout("waygent-patch-source-");
    const result = await runWaygentDemo({ root, workspace });
    const runRoot = join(root, result.run_id);

    const state = JSON.parse(readFileSync(join(runRoot, "state.json"), "utf8")) as {
      tasks: Record<string, unknown>;
      provider_attempts: ProviderAttempt[];
    };
    const taskIds = Object.keys(state.tasks);
    expect(taskIds.length).toBeGreaterThan(0);

    const lastAttempt = state.provider_attempts[state.provider_attempts.length - 1]!;
    expect(typeof lastAttempt.worker_result_ref).toBe("string");

    const workerResult = JSON.parse(
      readFileSync(join(runRoot, lastAttempt.worker_result_ref as string), "utf8")
    ) as WorkerResult;
    expect(workerResult.status).toBe("completed");

    const patchRef = workerResult.evidence?.patch_ref;
    expect(typeof patchRef).toBe("string");
    expect((patchRef as string).startsWith("artifacts/worker/")).toBe(true);
    expect(existsSync(join(runRoot, patchRef as string))).toBe(true);
    expect(typeof workerResult.evidence!.patch_sha256).toBe("string");
    expect(typeof workerResult.evidence!.patch_byte_length).toBe("number");
  });

  test("adapter-crashed worker_result preserves salvage patch evidence when worktree changed", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-crash-patch-orch-"));
    const workspace = initSourceCheckout("waygent-crash-patch-source-");
    const script = `
      import { writeFileSync } from "node:fs";
      writeFileSync("provider-crash.txt", "written before crash\\n");
      console.error("provider crashed after writing a candidate patch");
      process.exit(2);
    `;

    await runWaygent({
      root,
      workspace,
      run_id: "run_crash_patch",
      plan: [
        "```yaml waygent-task",
        "id: task_provider_crash",
        "title: Process provider crashes after writing",
        "dependencies: []",
        "file_claims:",
        "  - path: provider-crash.txt",
        "    mode: owned",
        "risk: low",
        "verify:",
        "  - test -f provider-crash.txt",
        "```"
      ].join("\n"),
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: { codex: { executable: process.execPath, args: ["-e", script] } }
    });
    const runRoot = join(root, "run_crash_patch");
    const state = JSON.parse(readFileSync(join(runRoot, "state.json"), "utf8")) as {
      provider_attempts: ProviderAttempt[];
    };
    const attempt = state.provider_attempts.find((item) => item.task_id === "task_provider_crash")!;

    const workerResult = JSON.parse(
      readFileSync(join(runRoot, attempt.worker_result_ref as string), "utf8")
    ) as WorkerResult;
    expect(workerResult.status).toBe("failed");
    expect(workerResult.failure_class).toBe("adapter_crashed");
    expect(workerResult.evidence?.patch_salvaged).toBe(true);

    const patchRef = workerResult.evidence?.patch_ref;
    expect(typeof patchRef).toBe("string");
    expect((patchRef as string).startsWith("artifacts/worker/task_provider_crash/")).toBe(true);
    expect(readFileSync(join(runRoot, patchRef as string), "utf8")).toContain("provider-crash.txt");
    expect(typeof workerResult.evidence!.patch_sha256).toBe("string");
    expect(typeof workerResult.evidence!.patch_byte_length).toBe("number");
  });
});
