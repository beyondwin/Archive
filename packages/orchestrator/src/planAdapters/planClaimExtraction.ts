import type { FileClaim, FileClaimMode } from "@waygent/runway-control";
import { logicalCommandLines } from "./commandLines";

export interface ExtractedPlanTask {
  number: number;
  title: string;
  body: string;
  explicit_file_claims: FileClaim[];
  prose_file_claims: FileClaim[];
  fenced_commands: string[];
}

export interface ExtractedSuperpowersPlan {
  tasks: ExtractedPlanTask[];
}

const taskHeading = /^#{2,4}\s+(?:Task|작업|Phase)\s+(\d+)\s*[:.)-]?\s*(.*)$/gim;
const explicitClaim = /^\s*-\s+(Create|Modify|Read|Append):\s+`([^`]+)`/gim;
const fencedCommand = /```(?:bash|sh|shell)?\r?\n([\s\S]*?)\r?\n```/gim;
const inlinePath = /`([^`]+\.(?:ts|tsx|js|jsx|mjs|json|md|mdx|toml|yaml|yml|rs|py|sh|css|html|kt|kts|gradle|gradle\.kts|java|xml))`/g;

export function extractSuperpowersPlan(markdown: string): ExtractedSuperpowersPlan {
  const masked = maskFencedCodeBlocks(markdown);
  const headings = [...masked.matchAll(taskHeading)];
  const tasks = headings.map((match, index): ExtractedPlanTask => {
    const start = match.index ?? 0;
    const nextIndex = index + 1 < headings.length ? headings[index + 1]!.index : undefined;
    const end = typeof nextIndex === "number" ? nextIndex : markdown.length;
    const number = Number(match[1]);
    const title = (match[2] ?? "").trim() || `Task ${number}`;
    const body = markdown.slice(start, end);
    const explicit = extractExplicitFileClaims(body);
    const prose = extractProseFileClaims(body, explicit);
    return {
      number,
      title,
      body,
      explicit_file_claims: explicit,
      prose_file_claims: prose,
      fenced_commands: extractFencedCommands(body)
    };
  });
  return { tasks };
}

export function maskFencedCodeBlocks(markdown: string): string {
  return markdown.replace(
    /(^|\n)(```[^\n]*\n)([\s\S]*?)(\n```)/g,
    (_match, lead: string, opener: string, body: string, closer: string) => {
      const sanitized = body.replace(/[^\n]/g, " ");
      return `${lead}${opener}${sanitized}${closer}`;
    }
  );
}

export function extractExplicitFileClaims(section: string): FileClaim[] {
  const claims: FileClaim[] = [];
  for (const match of section.matchAll(explicitClaim)) {
    const verb = (match[1] ?? "").toLowerCase();
    const path = (match[2] ?? "").trim();
    if (!path || path.includes("..")) continue;
    claims.push({ path, mode: claimModeForVerb(verb) });
  }
  return dedupeClaims(claims);
}

export function extractProseFileClaims(section: string, explicitClaims: FileClaim[] = []): FileClaim[] {
  const explicitPaths = new Set(explicitClaims.map((claim) => claim.path));
  const claims: FileClaim[] = [];
  for (const match of section.matchAll(inlinePath)) {
    const path = (match[1] ?? "").trim();
    if (!path || path.includes("..") || explicitPaths.has(path)) continue;
    claims.push({ path, mode: inferClaimMode(section, path) });
  }
  return dedupeClaims(claims);
}

export function extractFencedCommands(section: string): string[] {
  const commands = [...section.matchAll(fencedCommand)].flatMap((match) =>
    logicalCommandLines(match[1] ?? "")
  );
  return [...new Set(commands)];
}

function claimModeForVerb(verb: string): FileClaimMode {
  if (verb === "read") return "read_only";
  if (verb === "append") return "shared_append";
  return "owned";
}

function inferClaimMode(body: string, path: string): FileClaimMode {
  const index = body.indexOf(path);
  const before = body.slice(Math.max(0, index - 80), index).toLowerCase();
  if (/\b(read|inspect|review)\b/.test(before)) return "read_only";
  if (/\b(append|add to)\b/.test(before)) return "shared_append";
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
