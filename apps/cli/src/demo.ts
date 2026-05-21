import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runWaygentDemo } from "@waygent/orchestrator";

const result = await runWaygentDemo({
  root: mkdtempSync(join(tmpdir(), "waygent-platform-demo-")),
  workspace: initDemoSourceCheckout(),
  run_id: "run_demo"
});

console.log(
  JSON.stringify(
    {
      run_id: result.run_id,
      trust_status: result.trust_report.trust_status,
      total_events: result.events.length,
      safe_wave: result.projection.safe_wave,
      apply_state: result.apply_state
    },
    null,
    2
  )
);

function initDemoSourceCheckout(): string {
  const workspace = mkdtempSync(join(tmpdir(), "waygent-platform-demo-source-"));
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
