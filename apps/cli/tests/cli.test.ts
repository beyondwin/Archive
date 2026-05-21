import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { parseCli, runCli } from "../src/index";

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

  test("supports stable command surface", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-clean-root-"));
    const workspace = mkdtempSync(join(tmpdir(), "waygent-clean-"));
    expect(await runCli(["apply", "--root", root, "--workspace", workspace, "--run", "run_demo"])).toMatchObject({
      command: "apply",
      status: "applied"
    });
    expect((await runCli(["intent", "--text", "최근 승인된 플랜 실행해줘"])) as { command: string }).toEqual({ command: "waygent run --latest" });
  });

  test("status reads a run created by run", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-cli-"));
    await runCli(["run", "--root", root, "--run", "run_cli"]);
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

    const result = await runCli(["run", "--workspace", workspace, "--root", root, "--latest", "--run", "run_latest"]);

    expect(result).toMatchObject({ run_id: "run_latest", projection: { safe_wave: ["task_real"] } });
  });

  test("events reads persisted run events", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-cli-events-"));
    await runCli(["run", "--root", root, "--run", "run_events"]);

    const result = await runCli(["events", "--root", root, "--run", "run_events"]);

    expect(result).toMatchObject({ run_id: "run_events", total_events: 6 });
    expect((result as { events: Array<{ event_type: string }> }).events[0]?.event_type).toBe("platform.run_started");
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
