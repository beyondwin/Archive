import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import type { ProviderAttempt, WorkerResult } from "@waygent/contracts";
import { runWaygentDemo } from "../src";
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
});
