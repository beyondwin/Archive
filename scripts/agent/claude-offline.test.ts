import { expect, test } from "bun:test";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { runClaudeOffline, type ClaudeOfflineCheck } from "./claude-offline";

const EXECUTOR = "skills/_legacy/kws-claude-multi-agent-executor";

type ObservedCheck = ClaudeOfflineCheck;

test("package gate runs every deterministic Claude check without changing baseline state", async () => {
  const root = process.cwd();
  const baseline = join(root, EXECUTOR, "evals/baselines/v3.0.0.json");
  const baselineBefore = await snapshotFile(baseline);
  const packageJson = JSON.parse(await readFile(join(root, "package.json"), "utf8")) as {
    scripts: Record<string, string>;
  };
  const kernelTests = (await readdir(join(root, EXECUTOR, "scripts/kernel")))
    .filter((name) => /^test_.*\.py$/.test(name))
    .sort();

  expect(packageJson.scripts["agent:claude-offline"]).toBe(
    "bun run scripts/agent/claude-offline.ts",
  );

  const child = Bun.spawn(["bun", "run", "agent:claude-offline"], {
    cwd: root,
    stdout: "pipe",
    stderr: "pipe",
  });
  const [exitCode, stdout, stderr] = await Promise.all([
    child.exited,
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
  ]);
  const baselineAfter = await snapshotFile(baseline);

  expect(exitCode, stderr).toBe(0);
  expect(stdout.split("\n").filter((line) => /^\[agent:claude-offline] /.test(line))).toEqual([
    "[agent:claude-offline] PASS compare-agentlens-events-self-test",
    ...kernelTests.map((name) => `[agent:claude-offline] PASS scripts/kernel/${name}`),
    "[agent:claude-offline] PASS doc-freshness-strict",
  ]);
  expect(baselineAfter).toEqual(baselineBefore);
});

test("injected discovery is sorted and the runner fails fast", async () => {
  expect(runClaudeOffline).toBeFunction();

  const calls: ObservedCheck[] = [];
  const stdout: string[] = [];
  const stderr: string[] = [];
  const exitCode = await runClaudeOffline({
    root: "/fixture",
    discoverKernelTests: async () => ["test_z.py", "notes.txt", "test_a.py"],
    run: async (check) => {
      calls.push(check);
      return check.id === "scripts/kernel/test_z.py" ? 9 : 0;
    },
    stdout: (line) => stdout.push(line),
    stderr: (line) => stderr.push(line),
  });

  expect(exitCode).toBe(9);
  expect(calls.map(({ id }) => id)).toEqual([
    "compare-agentlens-events-self-test",
    "scripts/kernel/test_a.py",
    "scripts/kernel/test_z.py",
  ]);
  expect(calls[0]?.cwd).toBe("/fixture/skills/_legacy/kws-claude-multi-agent-executor");
  expect(stdout).toEqual([
    "[agent:claude-offline] PASS compare-agentlens-events-self-test",
    "[agent:claude-offline] PASS scripts/kernel/test_a.py",
  ]);
  expect(stderr).toEqual([
    "[agent:claude-offline] FAIL scripts/kernel/test_z.py exit-code=9",
  ]);
});

test("injected runner receives the self-test, sorted Python tests, and strict doc check", async () => {
  expect(runClaudeOffline).toBeFunction();

  const calls: ObservedCheck[] = [];
  const exitCode = await runClaudeOffline({
    root: "/fixture",
    discoverKernelTests: async () => ["test_b.py", "ignored.py", "test_a.py"],
    run: async (check) => {
      calls.push(check);
      return 0;
    },
    stdout: () => {},
    stderr: () => {},
  });

  expect(exitCode).toBe(0);
  expect(calls.map(({ id, argv, cwd, env }) => ({ id, argv, cwd, env }))).toEqual([
    {
      id: "compare-agentlens-events-self-test",
      argv: ["python3", "scripts/compare_agentlens_events.py", "--self-test"],
      cwd: "/fixture/skills/_legacy/kws-claude-multi-agent-executor",
      env: undefined,
    },
    {
      id: "scripts/kernel/test_a.py",
      argv: ["python3", "scripts/kernel/test_a.py"],
      cwd: "/fixture/skills/_legacy/kws-claude-multi-agent-executor",
      env: undefined,
    },
    {
      id: "scripts/kernel/test_b.py",
      argv: ["python3", "scripts/kernel/test_b.py"],
      cwd: "/fixture/skills/_legacy/kws-claude-multi-agent-executor",
      env: undefined,
    },
    {
      id: "doc-freshness-strict",
      argv: ["python3", "evals/check_doc_freshness.py"],
      cwd: "/fixture/skills/_legacy/kws-claude-multi-agent-executor",
      env: { DOC_FRESHNESS_STRICT: "1" },
    },
  ]);
});

test("discovery exceptions return a stable failure without leaking absolute paths", async () => {
  const stderr: string[] = [];
  const result = runClaudeOffline({
    root: "/fixture",
    discoverKernelTests: async () => {
      throw new Error("cannot read /machine-specific/private/kernel");
    },
    run: async () => 0,
    stdout: () => {},
    stderr: (line) => stderr.push(line),
  });

  await expect(result).resolves.toBe(1);
  expect(stderr).toEqual([
    "[agent:claude-offline] FAIL discover-kernel-tests error=exception",
  ]);
});

test("runner exceptions return a stable failure for the current check", async () => {
  const stderr: string[] = [];
  const result = runClaudeOffline({
    root: "/fixture",
    discoverKernelTests: async () => [],
    run: async () => {
      throw new Error("launch failed at /machine-specific/python3");
    },
    stdout: () => {},
    stderr: (line) => stderr.push(line),
  });

  await expect(result).resolves.toBe(1);
  expect(stderr).toEqual([
    "[agent:claude-offline] FAIL compare-agentlens-events-self-test error=exception",
  ]);
});

async function snapshotFile(path: string): Promise<{ exists: false } | { exists: true; bytes: Uint8Array }> {
  const file = Bun.file(path);
  if (!await file.exists()) return { exists: false };
  return { exists: true, bytes: new Uint8Array(await file.arrayBuffer()) };
}
