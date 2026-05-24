import type { FileClaim, FileClaimMode } from "@waygent/runway-control";

export interface ExtractedPlanTask {
  number: number;
  title: string;
  body: string;
  line_start: number;
  explicit_file_claims: FileClaim[];
  prose_file_claims: FileClaim[];
  fenced_commands: string[];
  fenced_examples?: ExtractedFenceBlock[];
  command_candidates?: ExtractedCommandCandidate[];
}

export interface ExtractedFenceBlock {
  language: string | null;
  content: string;
  line_start: number;
  line_end: number;
  source: "command" | "example";
}

export interface ExtractedCommandCandidate {
  command: string;
  source: "shell_fence" | "prose_hint" | "diagnostic_hint";
  language: string | null;
  line_start: number;
  line_end: number;
}

export interface ExtractedSuperpowersPlan {
  tasks: ExtractedPlanTask[];
}

const taskHeading = /^#{2,4}\s+(?:Task|작업|Phase)\s+(\d+)\s*[:.)-]?\s*(.*)$/gim;
const explicitClaim = /^\s*-\s+(Create|Modify|Read|Append|Test):\s+`([^`]+)`/gim;
const inlinePath = /`([^`]+\.(?:ts|tsx|js|jsx|mjs|json|md|mdx|toml|yaml|yml|rs|py|sh|css|html|kt|kts|gradle|gradle\.kts|java|xml))`/g;
const shellFenceLanguages = new Set(["bash", "sh", "shell", "zsh"]);

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
    const lineStart = lineNumberAtIndex(markdown, start);
    const explicit = extractExplicitFileClaims(body);
    const prose = extractProseFileClaims(body, explicit);
    const fenced = extractFencedEvidence(body, lineStart - 1);
    const inlineRunCandidates = extractInlineRunCandidates(body, lineStart - 1);
    const commandCandidates = [...fenced.command_candidates, ...inlineRunCandidates];
    return {
      number,
      title,
      body,
      line_start: lineStart,
      explicit_file_claims: explicit,
      prose_file_claims: prose,
      fenced_commands: [...new Set(commandCandidates.map((candidate) => candidate.command))],
      fenced_examples: fenced.fenced_examples,
      command_candidates: commandCandidates
    };
  });
  return { tasks };
}

function extractInlineRunCandidates(section: string, lineOffset: number): ExtractedCommandCandidate[] {
  const candidates: ExtractedCommandCandidate[] = [];
  const lines = section.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    const match = line.match(/\bRun:\s*`([^`]+)`/i);
    if (!match) continue;
    const command = (match[1] ?? "").trim();
    if (!command) continue;
    const sourceLine = lineOffset + index + 1;
    candidates.push({
      command,
      source: "prose_hint",
      language: null,
      line_start: sourceLine,
      line_end: sourceLine
    });
  }
  return candidates;
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
  return extractFencedEvidence(section, 0).fenced_commands;
}

function extractFencedEvidence(
  section: string,
  lineOffset: number
): {
  fenced_commands: string[];
  fenced_examples: ExtractedFenceBlock[];
  command_candidates: ExtractedCommandCandidate[];
} {
  const blocks = scanFencedBlocks(section, lineOffset);
  const commandCandidates = blocks
    .filter((block) => block.source === "command")
    .flatMap((block) => extractCommandCandidates(block));
  return {
    fenced_commands: [...new Set(commandCandidates.map((candidate) => candidate.command))],
    fenced_examples: blocks.filter((block) => block.source === "example"),
    command_candidates: commandCandidates
  };
}

function scanFencedBlocks(section: string, lineOffset: number): ExtractedFenceBlock[] {
  const blocks: ExtractedFenceBlock[] = [];
  const lines = section.split(/\r?\n/);
  let active:
    | {
      fenceLength: number;
      language: string | null;
      openerLine: number;
      source: "command" | "example";
      contentLines: string[];
    }
    | null = null;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    const sourceLine = lineOffset + index + 1;

    if (active) {
      if (isFenceCloser(line, active.fenceLength)) {
        blocks.push({
          language: active.language,
          content: active.contentLines.join("\n"),
          line_start: active.openerLine,
          line_end: sourceLine,
          source: active.source
        });
        active = null;
        continue;
      }
      active.contentLines.push(line);
      continue;
    }

    const opener = parseFenceOpener(line);
    if (!opener) continue;
    active = {
      fenceLength: opener.fenceLength,
      language: opener.language,
      openerLine: sourceLine,
      source: fenceSource(lines, index, opener.language),
      contentLines: []
    };
  }

  if (active) {
    blocks.push({
      language: active.language,
      content: active.contentLines.join("\n"),
      line_start: active.openerLine,
      line_end: lineOffset + lines.length,
      source: active.source
    });
  }

  return blocks;
}

function extractCommandCandidates(block: ExtractedFenceBlock): ExtractedCommandCandidate[] {
  const candidates: ExtractedCommandCandidate[] = [];
  let current = "";
  let currentStart: number | null = null;
  const lines = block.content.split(/\r?\n/);
  const contentLineOffset = block.line_start;

  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = (lines[index] ?? "").trim();
    const sourceLine = contentLineOffset + index + 1;
    if (!trimmed || trimmed.startsWith("#")) continue;

    if (trimmed.endsWith("\\")) {
      if (currentStart === null) currentStart = sourceLine;
      current += `${trimmed.slice(0, -1).trim()} `;
      continue;
    }

    candidates.push({
      command: `${current}${trimmed}`.trim(),
      source: "shell_fence",
      language: block.language,
      line_start: currentStart ?? sourceLine,
      line_end: sourceLine
    });
    current = "";
    currentStart = null;
  }

  if (current.trim()) {
    candidates.push({
      command: current.trim(),
      source: "shell_fence",
      language: block.language,
      line_start: currentStart ?? block.line_start + 1,
      line_end: block.line_start + lines.length
    });
  }

  return candidates;
}

function parseFenceOpener(line: string): { fenceLength: number; language: string | null } | null {
  const match = line.match(/^\s*(`{3,})([^`]*)$/);
  if (!match) return null;
  return {
    fenceLength: match[1]!.length,
    language: normalizeFenceLanguage(match[2] ?? "")
  };
}

function isFenceCloser(line: string, fenceLength: number): boolean {
  const match = line.match(/^\s*(`{3,})\s*$/);
  return match ? match[1]!.length >= fenceLength : false;
}

function normalizeFenceLanguage(info: string): string | null {
  const language = info.trim().split(/\s+/, 1)[0]?.toLowerCase() ?? "";
  return language || null;
}

function isShellFence(language: string | null): boolean {
  return language !== null && shellFenceLanguages.has(language);
}

function fenceSource(
  lines: ReadonlyArray<string>,
  openerIndex: number,
  language: string | null
): "command" | "example" {
  if (!isShellFence(language)) return "example";
  const previous = previousNonEmptyLine(lines, openerIndex);
  const step = previousStepLine(lines, openerIndex);
  if (isNonVerificationIntentLine(previous)) return "example";
  if (step && isNonVerificationStepLine(step)) return "example";
  return "command";
}

function previousNonEmptyLine(lines: ReadonlyArray<string>, beforeIndex: number): string {
  for (let index = beforeIndex - 1; index >= 0; index -= 1) {
    const line = (lines[index] ?? "").trim();
    if (line) return line;
  }
  return "";
}

function previousStepLine(lines: ReadonlyArray<string>, beforeIndex: number): string {
  for (let index = beforeIndex - 1; index >= 0; index -= 1) {
    const line = (lines[index] ?? "").trim();
    if (!line) continue;
    if (/^#{2,6}\s+/.test(line) || /^\s*-\s+\[[ xX]\]\s+/.test(line)) return line;
  }
  return "";
}

function isVerificationIntentLine(line: string): boolean {
  return /^(run|verify|verification|checks?|test|tests|final checks?|final verification):$/i.test(line.trim());
}

function isNonVerificationIntentLine(line: string): boolean {
  const normalized = line.trim();
  return /^(example|examples?|commit|checkpoint|optional|notes?):$/i.test(normalized) ||
    (!isVerificationIntentLine(normalized) && /^(example|commit|checkpoint|optional)\b/i.test(normalized));
}

function isNonVerificationStepLine(line: string): boolean {
  return /\b(commit|checkpoint|example|optional|when checkout exists|external smoke|graphify|refresh graphify|post-apply)\b/i.test(line);
}

function lineNumberAtIndex(text: string, index: number): number {
  return text.slice(0, index).split(/\r?\n/).length;
}

function claimModeForVerb(verb: string): FileClaimMode {
  if (verb === "read") return "read_only";
  if (verb === "append") return "shared_append";
  return "owned";
}

function inferClaimMode(body: string, path: string): FileClaimMode {
  const index = body.indexOf(path);
  const before = body.slice(Math.max(0, index - 80), index).toLowerCase();
  const readIndex = Math.max(before.lastIndexOf("read"), before.lastIndexOf("inspect"), before.lastIndexOf("review"));
  const appendIndex = Math.max(before.lastIndexOf("append"), before.lastIndexOf("add to"));
  const writeIndex = Math.max(
    before.lastIndexOf("update"),
    before.lastIndexOf("modify"),
    before.lastIndexOf("change"),
    before.lastIndexOf("create"),
    before.lastIndexOf("write")
  );
  if (appendIndex > readIndex && appendIndex > writeIndex) return "shared_append";
  if (readIndex > writeIndex) return "read_only";
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
