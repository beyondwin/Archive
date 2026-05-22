import type { RiskLevel } from "@waygent/contracts";
import type { FileClaim, FileClaimMode } from "@waygent/runway-control";
import { hasWaygentTaskBlock } from "./planParser";
import { scaffoldWaygentTask } from "./planScaffold";
import { extractInstructionLines } from "./planAdapters/instructionsExtract";
import {
  buildProjectScriptCatalog,
  isCommandInCatalog,
  type ProjectScriptCatalog
} from "./planAdapters/projectScriptCatalog";
import { inferRiskLevel } from "./planAdapters/riskInference";
import { detectVerifyTheater } from "./planAdapters/verifyQuality";

export interface NormalizeWaygentPlanInput {
  markdown: string;
  path: string | null;
  workspace?: string;
  unsafe_verification?: boolean;
  infer_risk?: boolean;
}

export interface NormalizedWaygentPlan {
  markdown: string;
  path: string | null;
  mode: "native" | "superpowers";
  task_count: number;
  diagnostics: string[];
}

interface SuperpowersTaskSection {
  number: number;
  title: string;
  body: string;
}

interface NormalizedTaskInput {
  id: string;
  title: string;
  dependencies: string[];
  file_claims: FileClaim[];
  risk: RiskLevel;
  verify: string[];
  instructions: string[];
}

const TASK_HEADING = /^#{2,3}\s+Task\s+(\d+)\s*:\s*(.+)$/gim;
const FILE_CLAIM = /^\s*-\s+(Create|Modify|Read|Append):\s+`([^`]+)`/gim;
const RUN_BLOCK = /^Run(?:\s+[^:]*)?:\s*\r?\n\s*```(?:bash|sh|shell)?\r?\n([\s\S]*?)\r?\n```/gim;
const SAFE_COMMAND_STARTS = [
  "bun test",
  "bun run test",
  "bun run check",
  "bun run typecheck",
  "bun run build",
  "bun run platform:demo",
  "bun run waygent:scenarios",
  "cargo test",
  "npm test",
  "npm run test",
  "pnpm test",
  "pnpm run test",
  "yarn test",
  "test ",
  "printf ",
  "git diff --check"
];

export function normalizeWaygentPlanInput(input: NormalizeWaygentPlanInput): NormalizedWaygentPlan {
  if (hasWaygentTaskBlock(input.markdown)) {
    return {
      markdown: input.markdown,
      path: input.path,
      mode: "native",
      task_count: 0,
      diagnostics: []
    };
  }

  const sections = extractSuperpowersTaskSections(input.markdown);
  if (sections.length === 0) {
    return {
      markdown: input.markdown,
      path: input.path,
      mode: "native",
      task_count: 0,
      diagnostics: []
    };
  }

  const catalog = input.workspace ? buildProjectScriptCatalog(input.workspace) : null;
  const unsafeVerification = input.unsafe_verification === true;
  const useInferredRisk = input.infer_risk === true || catalog !== null;
  const errors: string[] = [];
  const diagnostics: string[] = [];
  const tasks: NormalizedTaskInput[] = [];

  for (const section of sections) {
    const fileClaims = extractFileClaims(section.body);
    const verify = extractVerificationCommands(section.body, catalog);
    if (fileClaims.length === 0) {
      const message = `Task ${section.number} "${section.title}" is missing explicit file claims`;
      (unsafeVerification ? diagnostics : errors).push(message);
    }
    if (verify.length === 0) {
      const message = `Task ${section.number} "${section.title}" is missing safe verification commands`;
      (unsafeVerification ? diagnostics : errors).push(message);
    }

    const risk: RiskLevel = useInferredRisk
      ? inferRiskLevel({
          title: section.title,
          body: section.body,
          file_claims: fileClaims
        }).risk
      : "high";

    const theater = detectVerifyTheater({ verify, file_claims: fileClaims });
    if (theater.is_theater) {
      diagnostics.push(
        `Task ${section.number} "${section.title}" verification quality warning: ${theater.reasons.join("; ")}`
      );
    }

    tasks.push({
      id: `task_${section.number}_${slugify(section.title)}`,
      title: section.title,
      dependencies: tasks.length > 0 ? [tasks[tasks.length - 1]!.id] : [],
      file_claims: fileClaims,
      risk,
      verify,
      instructions: extractInstructionLines(section.body)
    });
  }

  const coverageErrors = verificationClaimCoverageErrors(tasks);
  if (unsafeVerification) {
    diagnostics.push(...coverageErrors);
  } else {
    errors.push(...coverageErrors);
  }

  if (errors.length > 0) {
    throw new Error([
      `cannot normalize superpowers implementation plan into an executable Waygent plan${input.path ? `: ${input.path}` : ""}.`,
      ...errors.map((error) => `- ${error}`),
      "Add one or more fenced ```yaml waygent-task blocks, or run waygent scaffold-plan with explicit file claims, risk, and verification commands."
    ].join("\n"));
  }

  if (useInferredRisk) {
    const riskCounts = countRisks(tasks);
    diagnostics.unshift(
      `risk inferred for ${tasks.length} normalized tasks (low=${riskCounts.low}, medium=${riskCounts.medium}, high=${riskCounts.high})`
    );
  } else {
    diagnostics.unshift(`risk defaulted to high for ${tasks.length} normalized tasks`);
  }
  if (catalog) {
    diagnostics.push(`project script catalog applied (${catalog.commands.size} commands)`);
  }
  if (unsafeVerification) {
    diagnostics.push("unsafe_verification: strict claim/verification checks downgraded to warnings");
  }

  return {
    markdown: [
      "# Normalized Waygent Plan",
      "",
      `Source: ${input.path ?? "inline"}`,
      "",
      ...tasks.map((task) => scaffoldWaygentTask(task))
    ].join("\n"),
    path: input.path,
    mode: "superpowers",
    task_count: tasks.length,
    diagnostics
  };
}

export function isNormalizableSuperpowersPlan(markdown: string): boolean {
  if (hasWaygentTaskBlock(markdown)) return true;
  const sections = extractSuperpowersTaskSections(markdown);
  if (sections.length === 0) return false;
  return sections.some(
    (section) =>
      extractFileClaims(section.body).length > 0 &&
      extractVerificationCommands(section.body, null).length > 0
  );
}

function extractSuperpowersTaskSections(markdown: string): SuperpowersTaskSection[] {
  const headings = [...markdown.matchAll(TASK_HEADING)];
  return headings.map((match, index) => {
    const start = match.index ?? 0;
    const end =
      index + 1 < headings.length ? headings[index + 1]!.index ?? markdown.length : markdown.length;
    return {
      number: Number(match[1]),
      title: (match[2] ?? "").trim(),
      body: markdown.slice(start, end)
    };
  });
}

function extractFileClaims(section: string): FileClaim[] {
  const claims: FileClaim[] = [];
  for (const match of section.matchAll(FILE_CLAIM)) {
    const verb = (match[1] ?? "").toLowerCase();
    const path = (match[2] ?? "").trim();
    if (!path) continue;
    claims.push({
      path,
      mode: claimModeForVerb(verb)
    });
  }
  return dedupeClaims(claims);
}

function claimModeForVerb(verb: string): FileClaimMode {
  if (verb === "read") return "read_only";
  if (verb === "append") return "shared_append";
  return "owned";
}

function dedupeClaims(claims: FileClaim[]): FileClaim[] {
  const byPath = new Map<string, FileClaim>();
  for (const claim of claims) {
    const existing = byPath.get(claim.path);
    if (!existing || existing.mode === "read_only") byPath.set(claim.path, claim);
  }
  return [...byPath.values()];
}

function extractVerificationCommands(
  section: string,
  catalog: ProjectScriptCatalog | null
): string[] {
  const commands: string[] = [];
  for (const match of section.matchAll(RUN_BLOCK)) {
    commands.push(
      ...logicalCommandLines(match[1] ?? "").filter((cmd) =>
        isSafeVerificationCommand(cmd, catalog)
      )
    );
  }
  return [...new Set(commands)];
}

function isProviderInstructionCommand(command: string): boolean {
  const normalized = command.replace(/\s+/g, " ").trim();
  return !/^git\s+(add|commit|push|reset|checkout|merge|rebase|stash|clean|worktree)\b/.test(
    normalized
  );
}

function logicalCommandLines(raw: string): string[] {
  const commands: string[] = [];
  let current = "";
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    if (trimmed.endsWith("\\")) {
      current += `${trimmed.slice(0, -1).trim()} `;
      continue;
    }
    commands.push(`${current}${trimmed}`.trim());
    current = "";
  }
  if (current.trim()) commands.push(current.trim());
  return commands;
}

function isSafeVerificationCommand(
  command: string,
  catalog: ProjectScriptCatalog | null
): boolean {
  const normalized = command.replace(/\s+/g, " ").trim();
  if (!normalized) return false;
  const parts = normalized.split(/\s+&&\s+/);
  return parts.every((part, index) => {
    if (index === 0 && part.startsWith("cd ")) return true;
    if (SAFE_COMMAND_STARTS.some((prefix) => part === prefix.trim() || part.startsWith(prefix))) {
      return true;
    }
    if (catalog && isCommandInCatalog(part, catalog)) return true;
    return false;
  });
}

function verificationClaimCoverageErrors(tasks: NormalizedTaskInput[]): string[] {
  const allClaims = tasks.flatMap((task) => task.file_claims);
  const errors: string[] = [];
  for (const task of tasks) {
    for (const command of task.verify) {
      for (const path of explicitVerificationPaths(command)) {
        if (!allClaims.some((claim) => claimCoversPath(claim.path, path))) {
          errors.push(
            `Task ${task.id.replace(/^task_(\d+)_.*$/, "$1")} "${task.title}" verification command references unclaimed path ${path}`
          );
        }
      }
    }
  }
  return errors;
}

function explicitVerificationPaths(command: string): string[] {
  const paths = new Set<string>();
  for (const part of command.replace(/\s+/g, " ").trim().split(/\s+&&\s+/)) {
    const normalized = part.trim();
    if (normalized.startsWith("cd ")) continue;
    if (normalized.startsWith("bun test ")) {
      for (const token of commandTokens(normalized).slice(2)) {
        if (isExplicitPathToken(token)) paths.add(token);
      }
      continue;
    }
    if (normalized.startsWith("git diff --check")) {
      const tokens = commandTokens(normalized);
      const separatorIndex = tokens.indexOf("--");
      if (separatorIndex >= 0) {
        for (const token of tokens.slice(separatorIndex + 1)) {
          if (isExplicitPathToken(token)) paths.add(token);
        }
      }
    }
  }
  return [...paths];
}

function commandTokens(command: string): string[] {
  return command
    .split(/\s+/)
    .map((token) => token.replace(/^['"]|['"]$/g, ""))
    .filter(Boolean);
}

function isExplicitPathToken(token: string): boolean {
  if (!token || token.startsWith("-")) return false;
  return token.includes("/") || token.startsWith(".") || /\.[a-zA-Z0-9]+$/.test(token);
}

function claimCoversPath(claimPath: string, path: string): boolean {
  const normalizedClaim = claimPath.replace(/\/\*\*$/, "").replace(/\/$/, "");
  const normalizedPath = path.replace(/\/$/, "");
  return normalizedPath === normalizedClaim || normalizedPath.startsWith(`${normalizedClaim}/`);
}

function slugify(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return slug || "task";
}

function countRisks(tasks: ReadonlyArray<{ risk: RiskLevel }>): Record<RiskLevel, number> {
  const counts: Record<RiskLevel, number> = { low: 0, medium: 0, high: 0 };
  for (const task of tasks) counts[task.risk] += 1;
  return counts;
}

// Re-export instruction extractor for compatibility with any direct consumers.
export { extractInstructionLines };
