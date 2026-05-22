import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { appendDecisionFromWorker, renderDecisionsMarkdown } from "../src/decisions";
import { runWaygent } from "../src/orchestrator";
import { readRunStateV2 } from "../src/runState";

describe("decisions register", () => {
  test("ignores empty decisions and appends structured key decisions", () => {
    const state = {
      decisions_register: []
    } as Parameters<typeof appendDecisionFromWorker>[0];

    expect(appendDecisionFromWorker(state, {
      task_id: "task_a",
      changed_files: ["README.md"],
      evidence: { key_decision: "Use additive v2 fields", supersedes: null }
    })).toEqual(expect.objectContaining({ decision: "Use additive v2 fields" }));
    expect(appendDecisionFromWorker(state, {
      task_id: "task_b",
      changed_files: [],
      evidence: { key_decision: "n/a" }
    })).toBeNull();
    expect(state.decisions_register).toHaveLength(1);
  });

  test("renders an explicit empty markdown projection", () => {
    expect(renderDecisionsMarkdown("run_demo", [])).toContain("No runtime decisions recorded.");
  });

  test("injects prior decisions into subsequent task packets", async () => {
    const workspace = initSourceCheckout("waygent-decisions-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-decisions-root-"));
    const providerScript = join(root, "provider.js");
    writeFileSync(providerScript, `
let stdin = "";
for await (const chunk of Bun.stdin.stream()) stdin += new TextDecoder().decode(chunk);
const packetPath = stdin.match(/task_packet_path: ([^\\n]+)/)?.[1]?.trim();
const packet = packetPath ? await Bun.file(packetPath).json() : {};
const first = packet.task_id === "task_first";
await Bun.write(first ? "first.txt" : "second.txt", "ok\\n");
console.log(JSON.stringify({
  schema: "runway.worker_result.v1",
  task_id: packet.task_id,
  candidate_id: "candidate_" + packet.task_id,
  status: "completed",
  changed_files: [first ? "first.txt" : "second.txt"],
  summary: "ok",
  evidence: first ? { key_decision: "Persist decisions" } : { seen_decisions: packet.decisions }
}));
`);
    const plan = `
\`\`\`yaml waygent-task
id: task_first
title: First
dependencies: []
file_claims:
  - path: first.txt
    mode: owned
risk: low
verify:
  - test -f first.txt
\`\`\`
\`\`\`yaml waygent-task
id: task_second
title: Second
dependencies: [task_first]
file_claims:
  - path: second.txt
    mode: owned
risk: low
verify:
  - test -f second.txt
\`\`\`
`;

    await runWaygent({
      root,
      workspace,
      run_id: "run_decisions",
      plan,
      profile: { provider: "codex" },
      provider_processes: { codex: { executable: "bun", args: [providerScript] } }
    });

    const state = readRunStateV2(root, "run_decisions");
    expect(state.decisions_register?.[0]?.decision).toBe("Persist decisions");
    const packetPath = state.tasks.task_second?.task_packet_path;
    const packet = JSON.parse(readFileSync(String(packetPath), "utf8")) as { decisions: Array<{ summary: string }> };
    expect(packet.decisions).toEqual([{ decision_id: expect.any(String), summary: "Persist decisions" }]);
    expect(readFileSync(join(root, "run_decisions", "DECISIONS.md"), "utf8")).toContain("Persist decisions");
  });
});

function initSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  writeFileSync(join(workspace, "README.md"), "fixture\n");
  mkdirSync(join(workspace, "docs"), { recursive: true });
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
