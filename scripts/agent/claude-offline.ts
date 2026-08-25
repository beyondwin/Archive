import { readdir } from "node:fs/promises";
import { join, resolve } from "node:path";

const EXECUTOR_ROOT = "skills/_legacy/kws-claude-multi-agent-executor";

export interface ClaudeOfflineCheck {
  id: string;
  argv: readonly string[];
  cwd: string;
  env?: Record<string, string>;
}

export interface ClaudeOfflineOptions {
  root?: string;
  discoverKernelTests?: (directory: string) => Promise<readonly string[]>;
  run?: (check: ClaudeOfflineCheck) => Promise<number>;
  stdout?: (line: string) => void;
  stderr?: (line: string) => void;
}

export async function runClaudeOffline(
  options: ClaudeOfflineOptions = {},
): Promise<number> {
  const root = resolve(options.root ?? process.cwd());
  const executorRoot = join(root, EXECUTOR_ROOT);
  const discoverKernelTests = options.discoverKernelTests ?? readdir;
  const run = options.run ?? runCheck;
  const stdout = options.stdout ?? console.log;
  const stderr = options.stderr ?? console.error;
  let discoveredKernelTests: readonly string[];
  try {
    discoveredKernelTests = await discoverKernelTests(join(executorRoot, "scripts/kernel"));
  } catch {
    stderr("[agent:claude-offline] FAIL discover-kernel-tests error=exception");
    return 1;
  }
  const kernelTests = discoveredKernelTests
    .filter((name) => /^test_.*\.py$/.test(name))
    .sort(compare);
  const checks: ClaudeOfflineCheck[] = [
    {
      id: "compare-agentlens-events-self-test",
      argv: ["python3", "scripts/compare_agentlens_events.py", "--self-test"],
      cwd: executorRoot,
    },
    ...kernelTests.map((name) => ({
      id: `scripts/kernel/${name}`,
      argv: ["python3", `scripts/kernel/${name}`],
      cwd: executorRoot,
    })),
    {
      id: "doc-freshness-strict",
      argv: ["python3", "evals/check_doc_freshness.py"],
      cwd: executorRoot,
      env: { DOC_FRESHNESS_STRICT: "1" },
    },
  ];

  for (const check of checks) {
    let exitCode: number;
    try {
      exitCode = await run(check);
    } catch {
      stderr(`[agent:claude-offline] FAIL ${check.id} error=exception`);
      return 1;
    }
    if (exitCode !== 0) {
      stderr(`[agent:claude-offline] FAIL ${check.id} exit-code=${exitCode}`);
      return exitCode;
    }
    stdout(`[agent:claude-offline] PASS ${check.id}`);
  }
  return 0;
}

async function runCheck(check: ClaudeOfflineCheck): Promise<number> {
  const child = Bun.spawn([...check.argv], {
    cwd: check.cwd,
    env: { ...process.env, ...check.env },
    stdin: "ignore",
    stdout: "inherit",
    stderr: "inherit",
  });
  return child.exited;
}

function compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

if (import.meta.main) {
  process.exitCode = await runClaudeOffline();
}
