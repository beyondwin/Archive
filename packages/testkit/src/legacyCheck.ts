import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

export interface LegacyCheckResult {
  passed: boolean;
  violations: string[];
}

export function runLegacyCheck(root = process.cwd()): LegacyCheckResult {
  const scanRoots = ["apps", "packages", "native", "tests"];
  const activeRoutingRoots = [
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "skills/README.md",
    "docs/architecture",
    "docs/operations",
    "apps",
    "packages",
    "native",
    "tests"
  ];
  const violations: string[] = [];
  for (const scanRoot of scanRoots) {
    walk(join(root, scanRoot), root, violations);
  }
  if (existsSync(join(root, "skills", "agent-runway"))) {
    violations.push("skills/agent-runway: legacy AgentRunway skill directory must not exist");
  }
  for (const scanRoot of activeRoutingRoots) {
    walkActiveRouting(join(root, scanRoot), root, violations);
  }
  return { passed: violations.length === 0, violations };
}

function walk(path: string, root: string, violations: string[]): void {
  try {
    const stat = statSync(path);
    if (stat.isDirectory()) {
      for (const child of readdirSync(path)) {
        if (["node_modules", "target", "dist", "build"].includes(child)) continue;
        walk(join(path, child), root, violations);
      }
      return;
    }
    const rel = relative(root, path);
    if (rel.endsWith(".py")) violations.push(`${rel}: Python runtime file in product tree`);
    const text = readFileSync(path, "utf8");
    if (/(graphify\s+(update|query|build)|from\s+["'].*graphify|import\s+.*graphify)/i.test(text)) {
      violations.push(`${rel}: Graphify runtime dependency in product tree`);
    }
    if (
      /"event_type"\s*:\s*"(kws-cpe|kws-cme)\./.test(text)
      && !rel.endsWith("invalid-legacy-namespace.json")
    ) {
      violations.push(`${rel}: legacy KWS namespace in product tree`);
    }
  } catch {
    return;
  }
}

function walkActiveRouting(path: string, root: string, violations: string[]): void {
  try {
    const rel = relative(root, path);
    if (rel === "packages/testkit" || rel.startsWith("packages/testkit/")) return;
    const stat = statSync(path);
    if (stat.isDirectory()) {
      for (const child of readdirSync(path)) {
        if (["node_modules", "target", "dist", "build"].includes(child)) continue;
        walkActiveRouting(join(path, child), root, violations);
      }
      return;
    }
    const text = readFileSync(path, "utf8");
    if (
      /skills\/agent-runway|agentrunway\.py|agent-runway\s+(last|plan)|execution through AgentRunway|AgentRunway deterministic evals/.test(
        text
      )
    ) {
      violations.push(`${rel}: active AgentRunway routing reference`);
    }
  } catch {
    return;
  }
}

if (import.meta.main) {
  const result = runLegacyCheck();
  if (!result.passed) {
    console.error(result.violations.join("\n"));
    process.exit(1);
  }
  console.log("legacy checks passed");
}
