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
    "README.md",
    ".github",
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
    const rel = relative(root, path);
    if (isTestkitPath(rel)) return;
    const stat = statSync(path);
    if (stat.isDirectory()) {
      for (const child of readdirSync(path)) {
        if (["node_modules", "target", "dist", "build"].includes(child)) continue;
        walk(join(path, child), root, violations);
      }
      return;
    }
    if (rel.endsWith(".py")) violations.push(`${rel}: Python runtime file in product tree`);
    const text = readFileSync(path, "utf8");
    if (/(graphify\s+(update|query|build)|from\s+["'].*graphify|import\s+.*graphify)/i.test(text)) {
      violations.push(`${rel}: Graphify runtime dependency in product tree`);
    }
    if (/waygent\.run_state\.v1/.test(text)) {
      violations.push(`${rel}: legacy Waygent v1 state schema in product tree`);
    }
    if (/agentrunway-task/.test(text)) {
      violations.push(`${rel}: legacy AgentRunway task fence in product tree`);
    }
    if (/legacy_source/.test(text)) {
      violations.push(`${rel}: legacy projection source in product tree`);
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
    if (isTestkitPath(rel)) return;
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
    if (isHistoricalDoc(rel, text)) return;
    if (
      /AgentLens backend|AgentLens docs|AgentLens lives|AgentLens stores|AgentLens is the observability|components\/agentlens\/docs/.test(
        text
      )
      || /(?:^|\s)cd\s+components\/agentlens\b/.test(text)
      || (/\bpython(?:3)?\s+-m\s+pytest\b/.test(text) && /AgentLens|agentlens|components\/agentlens/.test(text))
    ) {
      violations.push(`${rel}: active Python AgentLens routing reference`);
    }
  } catch {
    return;
  }
}

function isTestkitPath(rel: string): boolean {
  return rel === "packages/testkit" || rel.startsWith("packages/testkit/");
}

function isHistoricalDoc(rel: string, text: string): boolean {
  return (
    rel.startsWith("docs/migration/")
    || rel.startsWith("docs/superpowers/")
    || /^> Status: historical\b/m.test(text)
  );
}

if (import.meta.main) {
  const result = runLegacyCheck();
  if (!result.passed) {
    console.error(result.violations.join("\n"));
    process.exit(1);
  }
  console.log("legacy checks passed");
}
