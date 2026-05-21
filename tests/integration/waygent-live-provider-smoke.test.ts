import { spawnSync } from "node:child_process";
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
    initGitWorkspace(workspace);

    const run = await runWaygentScenario(scenario, {
      root: mkdtempSync(join(tmpdir(), "waygent-live-provider-")),
      workspace,
      live_provider: liveProvider
    });

    expect(run.normalized.run_status).toBe("trusted");
    expect(run.normalized.apply_status).toBe("ready");
    expect(run.normalized.event_types).toContain("runway.worker_result");
    expect(run.normalized.checkpoints.some((ref) => ref.endsWith(".json"))).toBe(true);
    expect(run.normalized.combined_patch_ref?.endsWith(".patch")).toBe(true);
    const attempt = run.normalized.provider_attempts?.find((item) => item.task_id === "task_live_provider");
    expect(run.normalized.event_types.includes("runway.provider_attempt") || Boolean(attempt)).toBe(true);
    expect(attempt?.provider).toBe(liveProvider);
    expect(attempt?.stdout_ref?.endsWith(".stdout.txt")).toBe(true);
    expect(attempt?.stderr_ref?.endsWith(".stderr.txt")).toBe(true);
    expect(attempt?.worker_result_ref?.endsWith(".json")).toBe(true);
  }, 120000);
});

function initGitWorkspace(workspace: string): void {
  runGit(workspace, ["init", "-q"]);
  runGit(workspace, ["config", "user.email", "test@example.com"]);
  runGit(workspace, ["config", "user.name", "Waygent"]);
  runGit(workspace, ["add", "-A"]);
  runGit(workspace, ["commit", "-q", "-m", "base"]);
}

function runGit(workspace: string, args: string[]): void {
  const result = spawnSync("git", args, {
    cwd: workspace,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (result.status !== 0) {
    throw new Error(`git ${args.join(" ")} failed: ${result.stderr}`);
  }
}
