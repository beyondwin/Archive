import { access, readFile, stat } from "node:fs/promises";
import { constants } from "node:fs";
import { join, resolve } from "node:path";
import {
  CURRENT_GUIDANCE_FILES,
  LOCAL_STATE_PATTERN,
  REQUIRED_AGENT_FILES,
  REQUIRED_PATHS,
  type ContractIssue,
} from "./contract";

const REQUIRED_PACKAGE_SCRIPTS = {
  "agent:contract": "bun run scripts/agent/check-contract.ts",
} as const;

const EXECUTOR_GATES = [
  "skills/kws-codex-plan-executor/evals/run.sh",
  "skills/kws-claude-multi-agent-executor/evals/run.sh",
] as const;

const STALE_ACTIVE_PATH = /components\/agentlens/i;
const ACTIVE_CLAIM = /\b(?:active|current|primary)\b/i;
const RETIRED_CLAIM = /\b(?:removed|legacy|historical|retired|not)\b/i;

export interface CheckContractOptions {
  root?: string;
  requiredPaths?: readonly string[];
  requiredAgentFiles?: readonly string[];
  trackedFiles?: readonly string[];
}

export async function checkContract(
  options: CheckContractOptions = {},
): Promise<ContractIssue[]> {
  const root = resolve(options.root ?? process.cwd());
  const requiredPaths = options.requiredPaths ?? REQUIRED_PATHS;
  const requiredAgentFiles = options.requiredAgentFiles ?? REQUIRED_AGENT_FILES;
  const issues: ContractIssue[] = [];

  for (const path of requiredPaths) {
    if (!await exists(join(root, path))) {
      issues.push({
        code: "missing_active_path",
        path,
        message: "required active path is missing",
      });
    }
  }

  for (const path of requiredAgentFiles) {
    if (!await exists(join(root, path))) {
      issues.push({
        code: "missing_agent_file",
        path,
        message: "required agent guidance file is missing",
      });
    }
  }

  issues.push(...await checkGuidance(root));
  issues.push(...await checkPackageScripts(root));
  issues.push(...await checkExecutorGates(root));

  const trackedFiles = options.trackedFiles ?? await listTrackedFiles(root);
  for (const path of trackedFiles) {
    if (LOCAL_STATE_PATTERN.test(path)) {
      issues.push({
        code: "tracked_local_state",
        path,
        message: "local runtime state must not be tracked",
      });
    }
  }

  return issues;
}

export function formatContractIssues(
  issues: readonly ContractIssue[],
): string {
  return issues.map((issue) => `[${issue.code}] [${issue.path}] ${issue.message}`).join("\n");
}

async function checkGuidance(root: string): Promise<ContractIssue[]> {
  const issues: ContractIssue[] = [];

  for (const path of CURRENT_GUIDANCE_FILES) {
    const file = join(root, path);
    if (!await exists(file)) {
      issues.push({
        code: "stale_active_claim",
        path,
        message: "current guidance file is missing",
      });
      continue;
    }

    const lines = (await readFile(file, "utf8")).split("\n");
    if (lines.some((line) =>
      STALE_ACTIVE_PATH.test(line) && ACTIVE_CLAIM.test(line) && !RETIRED_CLAIM.test(line),
    )) {
      issues.push({
        code: "stale_active_claim",
        path,
        message: "guidance presents the removed components/agentlens path as active",
      });
    }
  }

  return issues;
}

async function checkPackageScripts(root: string): Promise<ContractIssue[]> {
  const path = "package.json";
  try {
    const packageJson = JSON.parse(await readFile(join(root, path), "utf8")) as {
      scripts?: Record<string, unknown>;
    };
    return Object.entries(REQUIRED_PACKAGE_SCRIPTS).flatMap(([name, command]) =>
      packageJson.scripts?.[name] === command
        ? []
        : [{
          code: "missing_package_script" as const,
          path,
          message: `missing required package script: ${name}`,
        }],
    );
  } catch {
    return [{
      code: "missing_package_script",
      path,
      message: "package.json is missing or invalid",
    }];
  }
}

async function checkExecutorGates(root: string): Promise<ContractIssue[]> {
  const issues: ContractIssue[] = [];
  for (const path of EXECUTOR_GATES) {
    try {
      await access(join(root, path), constants.X_OK);
      if (!(await stat(join(root, path))).isFile()) {
        throw new Error("executor gate is not a file");
      }
    } catch {
      issues.push({
        code: "non_executable_gate",
        path,
        message: "executor gate must be an executable file",
      });
    }
  }
  return issues;
}

async function listTrackedFiles(root: string): Promise<string[]> {
  const process = Bun.spawn(["git", "ls-files", "-z"], {
    cwd: root,
    stdout: "pipe",
    stderr: "ignore",
  });
  if (await process.exited !== 0) {
    return [];
  }
  return (await new Response(process.stdout).text()).split("\0").filter(Boolean);
}

async function exists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

if (import.meta.main) {
  const issues = await checkContract();
  if (issues.length === 0) {
    console.log("agent contract: PASS");
  } else {
    console.log(formatContractIssues(issues));
    process.exitCode = 1;
  }
}
