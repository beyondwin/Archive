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
    if (!await isReadableRegularFile(join(root, path))) {
      issues.push({
        code: "missing_agent_file",
        path,
        message: "required agent guidance file is missing or is not a readable regular file",
      });
    }
  }

  issues.push(...await checkGuidance(root));
  issues.push(...await checkPackageScripts(root));
  issues.push(...await checkExecutorGates(root));

  const scan = options.trackedFiles === undefined ? await listTrackedFiles(root) : undefined;
  if (scan?.issue) {
    issues.push(scan.issue);
  }
  const trackedFiles = options.trackedFiles ?? scan?.files ?? [];
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
    if (!await isReadableRegularFile(file)) {
      issues.push({
        code: "invalid_guidance_file",
        path,
        message: "current guidance file must be a readable regular file",
      });
      continue;
    }

    let contents: string;
    try {
      contents = await readFile(file, "utf8");
    } catch {
      issues.push({
        code: "invalid_guidance_file",
        path,
        message: "current guidance file could not be read",
      });
      continue;
    }

    if (hasStaleActiveClaim(contents)) {
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
      if (!(await stat(join(root, path))).isFile()) {
        throw new Error("executor gate is not a file");
      }
      await access(join(root, path), constants.X_OK);
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

async function listTrackedFiles(root: string): Promise<{
  files: string[];
  issue?: ContractIssue;
}> {
  try {
    const process = Bun.spawn(["git", "ls-files", "-z"], {
      cwd: root,
      stdout: "pipe",
      stderr: "ignore",
    });
    if (await process.exited !== 0) {
      return {
        files: [],
        issue: trackedFileScanIssue(),
      };
    }
    return { files: (await new Response(process.stdout).text()).split("\0").filter(Boolean) };
  } catch {
    return {
      files: [],
      issue: trackedFileScanIssue(),
    };
  }
}

async function exists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function isReadableRegularFile(path: string): Promise<boolean> {
  try {
    if (!(await stat(path)).isFile()) {
      return false;
    }
    await access(path, constants.R_OK);
    return true;
  } catch {
    return false;
  }
}

function hasStaleActiveClaim(contents: string): boolean {
  const normalized = contents.replace(/\s+/g, " ");
  for (const match of normalized.matchAll(/components\/agentlens/gi)) {
    const pathIndex = match.index ?? 0;
    const claim = normalized.slice(
      sentenceStart(normalized, pathIndex),
      sentenceEnd(normalized, pathIndex + match[0].length),
    );
    if (ACTIVE_CLAIM.test(claim) && !RETIRED_CLAIM.test(claim)) {
      return true;
    }
  }
  return false;
}

function sentenceStart(contents: string, index: number): number {
  return Math.max(
    contents.lastIndexOf(".", index - 1),
    contents.lastIndexOf("!", index - 1),
    contents.lastIndexOf("?", index - 1),
  ) + 1;
}

function sentenceEnd(contents: string, index: number): number {
  const endings = [
    contents.indexOf(".", index),
    contents.indexOf("!", index),
    contents.indexOf("?", index),
  ].filter((ending) => ending !== -1);
  return endings.length === 0 ? contents.length : Math.min(...endings);
}

function trackedFileScanIssue(): ContractIssue {
  return {
    code: "tracked_file_scan_failed",
    path: "git ls-files -z",
    message: "unable to list tracked files",
  };
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
