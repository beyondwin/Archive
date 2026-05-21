import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runWaygentScenario, type WaygentScenario } from "../../packages/testkit/src";

const liveProvider = process.env.WAYGENT_LIVE_PROVIDER;
const maybeTest = liveProvider ? test : test.skip;

describe("waygent live provider smoke", () => {
  maybeTest("runs a single task through the selected live provider", async () => {
    if (liveProvider !== "codex" && liveProvider !== "claude") {
      throw new Error("WAYGENT_LIVE_PROVIDER must be codex or claude");
    }

    const scenario: WaygentScenario = {
      id: "live-provider-smoke",
      title: "Live provider smoke",
      provider_fixture: "live-provider",
      source_dirty_before_apply: false,
      force_missing_checkpoint: false,
      plan: "```yaml waygent-task\nid: task_live_provider\ntitle: Live provider task\ndependencies: []\nfile_claims:\n  - path: live-provider.txt\n    mode: owned\nrisk: low\nverify:\n  - printf live\n```",
      expected: {
        run_status: "trusted",
        apply_status: "not_applied",
        event_types: []
      }
    };

    const workspace = mkdtempSync(join(tmpdir(), "waygent-live-provider-source-"));
    writeFileSync(join(workspace, "README.md"), "live provider smoke workspace\n");

    const run = await runWaygentScenario(scenario, {
      root: mkdtempSync(join(tmpdir(), "waygent-live-provider-")),
      workspace,
      live_provider: liveProvider
    });

    expect(run.normalized.run_status).toBe("trusted");
    expect(run.normalized.apply_status).toBe("not_applied");
    expect(run.normalized.event_types).toContain("runway.worker_result");
    expect(run.normalized.checkpoints).toEqual(["checkpoint_task_live_provider_candidate_task_live_provider"]);
  }, 120000);
});
