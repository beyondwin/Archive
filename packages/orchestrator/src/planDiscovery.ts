import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { basename, join, resolve } from "node:path";

export interface PlanDiscoveryOptions {
  workspace: string;
  plan_path?: string;
  latest?: boolean;
  topic?: string;
  inline_plan?: string;
}

export interface ResolvedPlanInput {
  markdown: string;
  path: string | null;
}

const PLAN_MARKER = /```yaml waygent-task\n/;
const SKIP_DIRS = new Set([".git", ".venv", "node_modules", "target", "tmp", "dist", "build"]);

export function resolvePlanInput(options: PlanDiscoveryOptions): ResolvedPlanInput {
  if (options.inline_plan?.trim()) {
    if (PLAN_MARKER.test(options.inline_plan)) return { markdown: options.inline_plan, path: null };
    const candidate = resolve(options.workspace, options.inline_plan);
    if (existsSync(candidate)) return readPlanFile(candidate);
    return { markdown: options.inline_plan, path: null };
  }
  if (options.plan_path) return readPlanFile(resolve(options.workspace, options.plan_path));
  if (options.latest || options.topic) return discoverPlan(options);
  throw new Error("plan input required; pass --plan, --latest, or --topic");
}

export function discoverPlan(options: PlanDiscoveryOptions): ResolvedPlanInput {
  const workspace = resolve(options.workspace);
  const candidates = collectMarkdownPlans(workspace)
    .map((path) => ({ path, markdown: readFileSync(path, "utf8") }))
    .filter((candidate) => PLAN_MARKER.test(candidate.markdown))
    .filter((candidate) => matchesTopic(candidate.path, candidate.markdown, options.topic));

  if (candidates.length === 0) {
    throw new Error(options.topic ? `no Waygent plan found for topic ${options.topic}` : "no Waygent plan found");
  }

  candidates.sort((left, right) => planRank(right.path) - planRank(left.path) || right.path.localeCompare(left.path));
  return { markdown: candidates[0]!.markdown, path: candidates[0]!.path };
}

function readPlanFile(path: string): ResolvedPlanInput {
  if (!existsSync(path)) throw new Error(`plan not found: ${path}`);
  return { markdown: readFileSync(path, "utf8"), path };
}

function collectMarkdownPlans(workspace: string): string[] {
  const roots = [
    workspace,
    join(workspace, "docs"),
    join(workspace, "docs", "plan"),
    join(workspace, "docs", "migration"),
    join(workspace, "components", "agentlens", "docs", "plan")
  ];
  const out = new Set<string>();
  for (const root of roots) {
    if (existsSync(root)) walk(root, out, 0);
  }
  return [...out];
}

function walk(dir: string, out: Set<string>, depth: number): void {
  if (depth > 6) return;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) walk(join(dir, entry.name), out, depth + 1);
      continue;
    }
    if (entry.isFile() && entry.name.endsWith(".md")) out.add(join(dir, entry.name));
  }
}

function matchesTopic(path: string, markdown: string, topic?: string): boolean {
  if (!topic) return true;
  const terms = topic.toLowerCase().split(/\s+/).filter(Boolean);
  const haystack = `${basename(path)}\n${markdown.slice(0, 4000)}`.toLowerCase();
  return terms.every((term) => haystack.includes(term));
}

function planRank(path: string): number {
  const stat = statSync(path);
  const nameDate = basename(path).match(/(20\d{2})-(\d{2})-(\d{2})/);
  if (nameDate) return Number(`${nameDate[1]}${nameDate[2]}${nameDate[3]}`);
  return Math.floor(stat.mtimeMs);
}
