import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runCli } from "../src/index";

const plan = `
\`\`\`yaml waygent-task
id: task_autogen
title: Auto-gen run id
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`;

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

describe("CLI auto-generates run_id when --run is omitted", () => {
  test("derives a unique timestamped slug from the plan basename", async () => {
    const workspace = initSourceCheckout("waygent-autogen-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-autogen-root-"));
    writeFileSync(join(workspace, "2026-05-22-autogen-plan.md"), plan);

    const result = await runCli([
      "run",
      "--provider", "fake",
      "--workspace", workspace,
      "--root", root,
      "--plan", "2026-05-22-autogen-plan.md"
    ]) as { run_id: string };

    expect(result.run_id).not.toBe("run_demo");
    expect(result.run_id).toMatch(/^autogen_plan_\d{8}_\d{6}(_\d+)?$/);
  });

  test("slugs an undated plan basename into the run_id", async () => {
    const workspace = initSourceCheckout("waygent-autogen-bare-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-autogen-bare-root-"));
    writeFileSync(join(workspace, "plan.md"), plan);

    const result = await runCli([
      "run",
      "--provider", "fake",
      "--workspace", workspace,
      "--root", root,
      "--plan", "plan.md"
    ]) as { run_id: string };

    expect(result.run_id).toMatch(/^plan_\d{8}_\d{6}(_\d+)?$/);
    expect(result.run_id).not.toBe("run_demo");
  });

  test("respects an explicit --run id when provided", async () => {
    const workspace = initSourceCheckout("waygent-autogen-explicit-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-autogen-explicit-root-"));
    writeFileSync(join(workspace, "plan.md"), plan);

    const result = await runCli([
      "run",
      "--provider", "fake",
      "--workspace", workspace,
      "--root", root,
      "--run", "run_explicit_autogen",
      "--plan", "plan.md"
    ]) as { run_id: string };

    expect(result.run_id).toBe("run_explicit_autogen");
  });
});
