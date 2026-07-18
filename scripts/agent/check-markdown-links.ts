import { readFile, stat } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

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
      if (!isWithinRoot(root, resolvedTarget) || !await exists(resolvedTarget)) {
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
  const masked = maskMarkdownContexts(contents);
  const targets: string[] = [];

  for (let index = 0; index < masked.length; index += 1) {
    if (masked[index] !== "[" || isEscaped(masked, index)) continue;
    const labelEnd = findBalancedLabelEnd(masked, index);
    if (labelEnd === -1 || masked[labelEnd + 1] !== "(") continue;
    const destination = parseInlineDestination(masked, labelEnd + 2);
    if (destination === undefined) continue;
    targets.push(destination.target);
    index = destination.end;
  }

  for (let lineStart = 0; lineStart < masked.length;) {
    const lineEnd = masked.indexOf("\n", lineStart);
    const end = lineEnd === -1 ? masked.length : lineEnd;
    const target = parseReferenceDestination(masked.slice(lineStart, end));
    if (target !== undefined) targets.push(target);
    lineStart = lineEnd === -1 ? masked.length : lineEnd + 1;
  }
  return targets;
}

function normalizeLocalTarget(target: string): string | undefined {
  const trimmed = target.trim();
  if (trimmed === "") return undefined;

  const fragmentIndex = trimmed.indexOf("#");
  const queryIndex = trimmed.indexOf("?");
  const end = Math.min(
    fragmentIndex === -1 ? trimmed.length : fragmentIndex,
    queryIndex === -1 ? trimmed.length : queryIndex,
  );
  const path = trimmed.slice(0, end);
  if (path === "") return undefined;

  let decoded: string;
  try {
    decoded = decodeURIComponent(path);
  } catch {
    decoded = path;
  }
  decoded = unescapeMarkdown(decoded).trim();
  if (
    decoded === "" || decoded.startsWith("#") || decoded.startsWith("?") ||
    decoded.startsWith("//") || /^[a-z][a-z\d+.-]*:/i.test(decoded)
  ) return undefined;
  return decoded;
}

function maskMarkdownContexts(contents: string): string {
  const masked = contents.split("");
  maskHtmlComments(masked);
  maskFencedCode(masked);
  maskInlineCode(masked);
  return masked.join("");
}

function maskHtmlComments(contents: string[]): void {
  const source = contents.join("");
  for (let start = source.indexOf("<!--"); start !== -1;) {
    const close = source.indexOf("-->", start + 4);
    const end = close === -1 ? source.length : close + 3;
    maskRange(contents, start, end);
    start = source.indexOf("<!--", end);
  }
}

function maskFencedCode(contents: string[]): void {
  let fence: { marker: string; length: number } | undefined;
  for (let lineStart = 0; lineStart < contents.length;) {
    const newline = contents.indexOf("\n", lineStart);
    const lineEnd = newline === -1 ? contents.length : newline;
    const line = contents.slice(lineStart, lineEnd).join("");
    const opening = /^ {0,3}(`{3,}|~{3,})/.exec(line);
    const closing = fence === undefined
      ? false
      : new RegExp(`^ {0,3}\\${fence.marker}{${fence.length},}[ \\t]*$`).test(line);

    if (fence !== undefined || opening !== null) {
      maskRange(contents, lineStart, newline === -1 ? lineEnd : newline + 1);
    }
    if (fence === undefined && opening !== null) {
      fence = { marker: opening[1]![0]!, length: opening[1]!.length };
    } else if (fence !== undefined && closing) {
      fence = undefined;
    }
    lineStart = newline === -1 ? contents.length : newline + 1;
  }
}

function maskInlineCode(contents: string[]): void {
  const source = contents.join("");
  for (let index = 0; index < source.length;) {
    if (source[index] !== "`" || contents[index] === " ") {
      index += 1;
      continue;
    }
    const length = markerRunLength(source, index, "`");
    const marker = "`".repeat(length);
    let close = source.indexOf(marker, index + length);
    while (close !== -1 && (source[close - 1] === "`" || source[close + length] === "`")) {
      close = source.indexOf(marker, close + length);
    }
    if (close === -1) {
      index += length;
      continue;
    }
    maskRange(contents, index, close + length);
    index = close + length;
  }
}

function maskRange(contents: string[], start: number, end: number): void {
  for (let index = start; index < end; index += 1) {
    if (contents[index] !== "\n" && contents[index] !== "\r") contents[index] = " ";
  }
}

function markerRunLength(contents: string, start: number, marker: string): number {
  let end = start;
  while (contents[end] === marker) end += 1;
  return end - start;
}

function findBalancedLabelEnd(contents: string, start: number): number {
  let depth = 0;
  for (let index = start; index < contents.length; index += 1) {
    if (isEscaped(contents, index)) continue;
    if (contents[index] === "[") depth += 1;
    if (contents[index] === "]" && --depth === 0) return index;
  }
  return -1;
}

function parseInlineDestination(
  contents: string,
  start: number,
): { target: string; end: number } | undefined {
  let index = skipWhitespace(contents, start);
  if (contents[index] === "<") {
    const targetStart = index + 1;
    const targetEnd = findUnescaped(contents, ">", targetStart);
    if (targetEnd === -1) return undefined;
    const end = findOuterLinkEnd(contents, targetEnd + 1);
    return end === -1 ? undefined : { target: contents.slice(targetStart, targetEnd), end };
  }

  const targetStart = index;
  let depth = 0;
  while (index < contents.length) {
    const character = contents[index]!;
    if (character === "\\") {
      index += 2;
      continue;
    }
    if (character === "(") {
      depth += 1;
    } else if (character === ")") {
      if (depth === 0) return { target: contents.slice(targetStart, index), end: index };
      depth -= 1;
    } else if (/\s/.test(character) && depth === 0) {
      const end = findOuterLinkEnd(contents, index);
      return end === -1 ? undefined : { target: contents.slice(targetStart, index), end };
    }
    index += 1;
  }
  return undefined;
}

function findOuterLinkEnd(contents: string, start: number): number {
  let depth = 0;
  let quote: string | undefined;
  for (let index = start; index < contents.length; index += 1) {
    const character = contents[index]!;
    if (character === "\\") {
      index += 1;
      continue;
    }
    if (quote !== undefined) {
      if (character === quote) quote = undefined;
      continue;
    }
    if (character === "\"" || character === "'") {
      quote = character;
    } else if (character === "(") {
      depth += 1;
    } else if (character === ")") {
      if (depth === 0) return index;
      depth -= 1;
    }
  }
  return -1;
}

function parseReferenceDestination(line: string): string | undefined {
  const indentation = /^ {0,3}/.exec(line)?.[0].length ?? 0;
  if (line[indentation] !== "[") return undefined;
  const labelEnd = findBalancedLabelEnd(line, indentation);
  if (labelEnd === -1 || line[labelEnd + 1] !== ":") return undefined;
  let index = skipWhitespace(line, labelEnd + 2);
  if (line[index] === "<") {
    const end = findUnescaped(line, ">", index + 1);
    return end === -1 ? undefined : line.slice(index + 1, end);
  }
  const start = index;
  while (index < line.length && !/\s/.test(line[index]!)) {
    if (line[index] === "\\") index += 1;
    index += 1;
  }
  return line.slice(start, index);
}

function skipWhitespace(contents: string, start: number): number {
  let index = start;
  while (/\s/.test(contents[index] ?? "")) index += 1;
  return index;
}

function findUnescaped(contents: string, target: string, start: number): number {
  for (let index = start; index < contents.length; index += 1) {
    if (contents[index] === target && !isEscaped(contents, index)) return index;
  }
  return -1;
}

function isEscaped(contents: string, index: number): boolean {
  let slashes = 0;
  for (let cursor = index - 1; cursor >= 0 && contents[cursor] === "\\"; cursor -= 1) {
    slashes += 1;
  }
  return slashes % 2 === 1;
}

function unescapeMarkdown(value: string): string {
  let result = "";
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index]!;
    const next = value[index + 1];
    if (character === "\\" && next !== undefined && isAsciiPunctuation(next)) {
      result += next;
      index += 1;
    } else {
      result += character;
    }
  }
  return result;
}

function isAsciiPunctuation(value: string): boolean {
  const code = value.charCodeAt(0);
  return (code >= 0x21 && code <= 0x2f) || (code >= 0x3a && code <= 0x40) ||
    (code >= 0x5b && code <= 0x60) || (code >= 0x7b && code <= 0x7e);
}

function isWithinRoot(root: string, target: string): boolean {
  const path = relative(root, target);
  return path === "" || (!isAbsolute(path) && path !== ".." && !path.startsWith(`..${sep}`));
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
