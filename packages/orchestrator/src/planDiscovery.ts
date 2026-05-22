import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { hasWaygentTaskBlock } from "./planParser";
import { isNormalizableSuperpowersPlan } from "./planNormalizer";

export interface PlanDiscoveryOptions {
  workspace: string;
  plan_path?: string;
  latest?: boolean;
  topic?: string;
  inline_plan?: string;
}

export interface SpecDiscoveryOptions {
  workspace: string;
  spec?: string;
}

export interface ResolvedPlanInput {
  markdown: string;
  path: string | null;
}

const SKIP_DIRS = new Set([".git", ".venv", "node_modules", "target", "tmp", "dist", "build"]);

export function resolvePlanInput(options: PlanDiscoveryOptions): ResolvedPlanInput {
  if (options.inline_plan?.trim()) {
    if (hasWaygentTaskBlock(options.inline_plan)) return { markdown: options.inline_plan, path: null };
    const candidate = resolve(options.workspace, options.inline_plan);
    if (existsSync(candidate)) return readPlanFile(candidate);
    if (!options.plan_path && !options.latest && !options.topic) return { markdown: options.inline_plan, path: null };
  }
  if (options.plan_path) return readPlanFile(resolveMarkdownInput(options.workspace, options.plan_path, collectMarkdownPlans(options.workspace), "plan"));
  if (options.latest || options.topic) return discoverPlan(options);
  throw new Error("plan input required; pass --plan, --latest, or --topic");
}

export function resolveSpecInput(options: SpecDiscoveryOptions): ResolvedPlanInput {
  if (!options.spec?.trim()) return { markdown: "", path: null };
  const resolved = resolveMarkdownInput(options.workspace, options.spec, collectMarkdownSpecs(options.workspace), "spec");
  if (existsSync(resolved)) return { markdown: readFileSync(resolved, "utf8"), path: resolved };
  if (isPathLikeMarkdownInput(options.spec)) throw new Error(`spec not found: ${resolved}`);
  return { markdown: options.spec, path: null };
}

export function discoverPlan(options: PlanDiscoveryOptions): ResolvedPlanInput {
  const workspace = resolve(options.workspace);
  const candidates = collectMarkdownPlans(workspace)
    .map((path) => ({ path, markdown: readFileSync(path, "utf8") }))
    .filter((candidate) => isRunnableWaygentPlan(candidate.markdown))
    .filter((candidate) => matchesTopic(candidate.path, candidate.markdown, options.topic));

  if (candidates.length === 0) {
    throw new Error(options.topic ? `no Waygent plan found for topic ${options.topic}` : "no Waygent plan found");
  }

  candidates.sort((left, right) => planRank(right.path) - planRank(left.path) || right.path.localeCompare(left.path));
  return { markdown: candidates[0]!.markdown, path: candidates[0]!.path };
}

function isRunnableWaygentPlan(markdown: string): boolean {
  return hasWaygentTaskBlock(markdown) || isNormalizableSuperpowersPlan(markdown);
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
    join(workspace, "docs", "plans"),
    join(workspace, "docs", "superpowers", "plans"),
    join(workspace, "docs", "migration"),
    join(workspace, "components", "agentlens", "docs", "plan")
  ];
  const out = new Set<string>();
  for (const root of roots) {
    if (existsSync(root)) walk(root, out, 0);
  }
  return [...out];
}

function collectMarkdownSpecs(workspace: string): string[] {
  const root = resolve(workspace);
  const roots = [
    root,
    join(root, "docs"),
    join(root, "docs", "specs"),
    join(root, "docs", "superpowers", "specs"),
    join(root, "docs", "architecture"),
    join(root, "docs", "migration"),
    join(root, "components", "agentlens", "docs"),
    join(root, "components", "agentlens", "docs", "specs")
  ];
  const out = new Set<string>();
  for (const candidateRoot of roots) {
    if (existsSync(candidateRoot)) walk(candidateRoot, out, 0);
  }
  return [...out];
}

function resolveMarkdownInput(workspace: string, input: string, candidates: string[], label: "plan" | "spec"): string {
  const direct = resolve(workspace, input);
  if (existsSync(direct)) return direct;
  if (!isBareFilename(input)) return direct;
  const matches = candidates.filter((candidate) => basename(candidate) === basename(input));
  if (matches.length === 1) return matches[0]!;
  if (matches.length > 1) {
    throw new Error(`ambiguous ${label} path ${input}; candidates: ${matches.join(", ")}`);
  }
  return direct;
}

function isBareFilename(input: string): boolean {
  const trimmed = input.trim();
  return trimmed === basename(trimmed) && !trimmed.includes("/") && !trimmed.includes("\\");
}

function isPathLikeMarkdownInput(input: string): boolean {
  const trimmed = input.trim();
  return trimmed.endsWith(".md") || trimmed.endsWith(".markdown") || trimmed.includes("/") || trimmed.includes("\\");
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
