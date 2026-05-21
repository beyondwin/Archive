import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readRunStateV2 } from "@waygent/orchestrator";
import { parseCli, resolveCliProfile, runCli } from "../src/index";

const plan = (id: string) => `
\`\`\`yaml waygent-task
id: ${id}
title: ${id}
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`;

describe("Waygent CLI", () => {
  test("parses run flags", () => {
    expect(parseCli(["run", "--plan", "plan.md", "--provider", "codex"]).flags.provider).toBe("codex");
  });

  test("defaults CLI run to Codex multi-agent while demo stays offline fake multi-agent", () => {
    expect(resolveCliProfile(parseCli(["run"]))).toMatchObject({
      provider: "codex",
      execution_mode: "multi-agent"
    });
    expect(resolveCliProfile(parseCli(["demo"]))).toMatchObject({
      provider: "fake",
      execution_mode: "multi-agent"
    });
  });

  test("refuses live providers for deterministic demo runs", () => {
    expect(() => resolveCliProfile(parseCli(["demo", "--provider", "codex"]))).toThrow(/waygent demo/);
  });

  test("root package exposes a stable waygent script", () => {
    const packageJson = JSON.parse(readFileSync(join(import.meta.dir, "..", "..", "..", "package.json"), "utf8")) as {
      scripts?: Record<string, string>;
    };

    expect(packageJson.scripts?.waygent).toBe("bun run apps/cli/src/index.ts");
  });

  test("supports stable command surface", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-clean-root-"));
    const workspace = mkdtempSync(join(tmpdir(), "waygent-clean-"));
    expect(await runCli(["apply", "--root", root, "--workspace", workspace, "--run", "run_demo"])).toMatchObject({
      command: "apply",
      status: "blocked",
      reason: "missing_run_state_v2"
    });
    expect((await runCli(["intent", "--text", "최근 승인된 플랜 실행해줘"])) as { command: string }).toEqual({ command: "waygent run --latest" });
  });

  test("status reads a run created by run", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-cli-"));
    await runCli(["run", "--provider", "fake", "--workspace", initSourceCheckout("waygent-cli-source-"), "--root", root, "--run", "run_cli"]);
    expect(await runCli(["status", "--root", root, "--last"])).toMatchObject({
      run_id: "run_cli",
      status: "completed"
    });
  });

  test("run --latest discovers and executes the newest local implementation plan", async () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-workspace-"));
    const root = mkdtempSync(join(tmpdir(), "waygent-runs-"));
    mkdirSync(join(workspace, "docs", "plan"), { recursive: true });
    writeFileSync(join(workspace, "docs", "plan", "2026-05-21-real-plan.md"), plan("task_real"));

    const result = await runCli(["run", "--provider", "fake", "--workspace", workspace, "--root", root, "--latest", "--run", "run_latest"]);

    expect(result).toMatchObject({ run_id: "run_latest", projection: { safe_wave: ["task_real"] } });
  });

  test("run resolves plan and spec basenames from approved docs directories", async () => {
    const workspace = initSourceCheckout("waygent-cli-basename-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-cli-basename-runs-"));
    mkdirSync(join(workspace, "docs", "superpowers", "plans"), { recursive: true });
    mkdirSync(join(workspace, "docs", "superpowers", "specs"), { recursive: true });
    writeFileSync(join(workspace, "docs", "superpowers", "plans", "2026-05-22-runtime.md"), plan("task_basename"));
    writeFileSync(join(workspace, "docs", "superpowers", "specs", "2026-05-22-runtime-design.md"), "# Runtime Design\n");

    await runCli([
      "run",
      "--provider", "fake",
      "--workspace", workspace,
      "--root", root,
      "--run", "run_basename",
      "--plan", "2026-05-22-runtime.md",
      "--spec", "2026-05-22-runtime-design.md"
    ]);

    const state = readRunStateV2(root, "run_basename");
    expect(state.plan_path?.endsWith("docs/superpowers/plans/2026-05-22-runtime.md")).toBe(true);
    expect(state.spec_path?.endsWith("docs/superpowers/specs/2026-05-22-runtime-design.md")).toBe(true);
  });

  test("scaffold-plan emits executable waygent-task markdown", async () => {
    const result = await runCli([
      "scaffold-plan",
      "--id", "task_cli_scaffold",
      "--title", "CLI scaffold",
      "--claim", "README.md:owned",
      "--risk", "low",
      "--verify", "printf hello"
    ]);

    expect(String((result as { markdown: string }).markdown)).toContain("```yaml waygent-task");
  });

  test("events reads persisted run events", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-cli-events-"));
    await runCli(["run", "--provider", "fake", "--workspace", initSourceCheckout("waygent-cli-events-source-"), "--root", root, "--run", "run_events"]);

    const result = await runCli(["events", "--root", root, "--run", "run_events"]);

    expect(result).toMatchObject({ run_id: "run_events", total_events: 9 });
    expect((result as { events: Array<{ event_type: string }> }).events[0]?.event_type).toBe("platform.run_started");
    expect((result as { events: Array<{ event_type: string }> }).events.map((event) => event.event_type))
      .toContain("runway.preflight_result");
  });

  test("apply refuses a dirty source checkout with an explicit blocker", async () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-dirty-"));
    writeFileSync(join(workspace, "dirty.txt"), "dirty");

    await expect(runCli(["apply", "--workspace", workspace, "--run", "run_dirty"])).resolves.toEqual({
      command: "apply",
      run_id: "run_dirty",
      status: "blocked",
      reason: "dirty_source_checkout"
    });
  });
});

function initSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  writeFileSync(join(workspace, "README.md"), "fixture\n");
  for (const args of [
    ["init", "-q"],
    ["config", "user.email", "test@example.com"],
    ["config", "user.name", "Waygent"],
    ["add", "-A"],
    ["commit", "-q", "-m", "init"]
  ]) {
    const result = Bun.spawnSync(["git", ...args], { cwd: workspace });
    if (result.exitCode !== 0) throw new Error(`git ${args.join(" ")} failed`);
  }
  return workspace;
}
