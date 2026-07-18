import { readFile, stat } from "node:fs/promises";
import { dirname, resolve } from "node:path";

export interface MarkdownLinkIssue {
  file: string;
  target: string;
}

export interface MarkdownLinkOptions {
  root: string;
  files: readonly string[];
  readText?: (path: string) => Promise<string>;
  exists?: (path: string) => Promise<boolean>;
}

export async function checkMarkdownLinks(
  options: MarkdownLinkOptions,
): Promise<MarkdownLinkIssue[]> {
  const root = resolve(options.root);
  const readText = options.readText ?? ((path: string) => readFile(path, "utf8"));
  const exists = options.exists ?? pathExists;
  const issues = new Map<string, MarkdownLinkIssue>();

  for (const file of options.files) {
    const documentPath = resolve(root, file);
    const contents = await readText(documentPath);
    for (const target of markdownTargets(contents)) {
      const localTarget = normalizeLocalTarget(target);
      if (localTarget === undefined) continue;

      const resolvedTarget = localTarget.startsWith("/")
        ? resolve(root, `.${localTarget}`)
        : resolve(dirname(documentPath), localTarget);
      if (!await exists(resolvedTarget)) {
        issues.set(`${file}\u0000${target}`, { file, target });
      }
    }
  }

  return [...issues.values()].sort((left, right) =>
    left.file === right.file
      ? compare(left.target, right.target)
      : compare(left.file, right.file)
  );
}

function markdownTargets(contents: string): string[] {
  const targets: string[] = [];
  const inlineLink = /!?\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)]+))(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\)/g;
  const referenceLink = /^\s{0,3}\[[^\]\n]+\]:\s*(?:<([^>\n]+)>|(\S+))/gm;

  for (const match of contents.matchAll(inlineLink)) {
    targets.push(match[1] ?? match[2] ?? "");
  }
  for (const match of contents.matchAll(referenceLink)) {
    targets.push(match[1] ?? match[2] ?? "");
  }
  return targets;
}

function normalizeLocalTarget(target: string): string | undefined {
  const trimmed = target.trim();
  if (
    trimmed === "" || trimmed.startsWith("#") || trimmed.startsWith("?") ||
    trimmed.startsWith("//") || /^[a-z][a-z\d+.-]*:/i.test(trimmed)
  ) {
    return undefined;
  }

  const fragmentIndex = trimmed.indexOf("#");
  const queryIndex = trimmed.indexOf("?");
  const end = Math.min(
    fragmentIndex === -1 ? trimmed.length : fragmentIndex,
    queryIndex === -1 ? trimmed.length : queryIndex,
  );
  const path = trimmed.slice(0, end);
  if (path === "") return undefined;

  try {
    return decodeURIComponent(path);
  } catch {
    return path;
  }
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

function compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

async function main(): Promise<number> {
  const files = process.argv.slice(2).filter((argument) => argument !== "--");
  const issues = await checkMarkdownLinks({ root: process.cwd(), files });
  for (const issue of issues) {
    console.error(`[markdown-link] [${issue.file}] missing local target: ${issue.target}`);
  }
  return issues.length === 0 ? 0 : 1;
}

if (import.meta.main) {
  process.exitCode = await main();
}
