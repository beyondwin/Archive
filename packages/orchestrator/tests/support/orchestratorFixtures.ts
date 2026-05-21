import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export function initSourceCheckout(prefix: string): string {
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

export function oneTaskPlan(taskId: string, path: string): string {
  return [
    "```yaml waygent-task",
    `id: ${taskId}`,
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
}
