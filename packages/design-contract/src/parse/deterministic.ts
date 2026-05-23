/**
 * Deterministic parser for canonical scaffold-shaped design and plan
 * markdown. Returns `{ kind: "ok", value }` on success or
 * `{ kind: "incomplete", reason }` when the source deviates from the
 * canonical shape — callers then fall through to the AI extractor.
 */

import { createHash } from "node:crypto";

export type DeterministicResult<T> =
  | { kind: "ok"; value: T }
  | { kind: "incomplete"; reason: IncompleteReason; details?: string };

export type IncompleteReason =
  | "missing_required_heading"
  | "ambiguous_paths_bound"
  | "unparseable_check_block"
  | "non_canonical_format";

export interface DesignDeterministicOutput {
  schema: "waygent.design_contract.v1";
  source_path: string;
  invariants: unknown[];
  prescriptive_blocks: PrescriptiveBlock[];
  parser: "deterministic";
  extraction_confidence: "high";
}

export interface PrescriptiveBlock {
  id: string;
  language: string;
  body: string;
  sha256: string;
}

export interface PlanDeterministicOutput {
  schema: "waygent.plan_contract.v1";
  source_path: string;
  tasks: unknown[];
  parser: "deterministic";
  extraction_confidence: "high";
}

interface TokenLine {
  indent: number;
  content: string;
}

const KEY_RE = /^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/;
const KEY_HEAD_RE = /^([A-Za-z_][A-Za-z0-9_-]*)\s*:/;
const HEADING_RE = /^(#+)\s+(.+?)\s*$/;

function tokenize(text: string): TokenLine[] {
  const out: TokenLine[] = [];
  for (const raw of text.split("\n")) {
    if (raw.trim() === "") continue;
    const indent = raw.length - raw.replace(/^[ \t]+/, "").length;
    const content = raw.slice(indent);
    if (content.startsWith("#")) continue;
    out.push({ indent, content });
  }
  return out;
}

function parseScalar(s: string): unknown {
  const t = s.trim();
  if (t === "") return null;
  if (t === "true") return true;
  if (t === "false") return false;
  if (t === "null") return null;
  if (/^-?\d+$/.test(t)) return Number(t);
  if (/^-?\d*\.\d+$/.test(t)) return Number(t);
  if (t.length >= 2 && t.startsWith('"') && t.endsWith('"')) {
    try {
      return JSON.parse(t);
    } catch {
      return t.slice(1, -1);
    }
  }
  if (t.length >= 2 && t.startsWith("'") && t.endsWith("'")) {
    return t.slice(1, -1);
  }
  return t;
}

class BlockParser {
  lines: TokenLine[];
  pos = 0;

  constructor(text: string) {
    this.lines = tokenize(text);
  }

  parseValueAt(indent: number): unknown {
    if (this.pos >= this.lines.length) return null;
    const line = this.lines[this.pos]!;
    if (line.indent < indent) return null;
    if (line.content.startsWith("-")) {
      return this.parseSequence(indent);
    }
    return this.parseMapping(indent);
  }

  parseMapping(indent: number): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    while (this.pos < this.lines.length) {
      const line = this.lines[this.pos]!;
      if (line.indent < indent) break;
      if (line.indent !== indent) break;
      const m = KEY_RE.exec(line.content);
      if (!m) break;
      const key = m[1]!;
      const valStr = m[2] ?? "";
      this.pos++;
      if (valStr === "") {
        result[key] = this.consumeNestedAfterKey(indent);
      } else {
        result[key] = parseScalar(valStr);
      }
    }
    return result;
  }

  consumeNestedAfterKey(parentIndent: number): unknown {
    if (this.pos >= this.lines.length) return null;
    const next = this.lines[this.pos]!;
    if (next.indent > parentIndent) {
      return this.parseValueAt(next.indent);
    }
    if (next.indent === parentIndent && next.content.startsWith("-")) {
      return this.parseSequence(parentIndent);
    }
    return null;
  }

  parseSequence(indent: number): unknown[] {
    const result: unknown[] = [];
    while (this.pos < this.lines.length) {
      const line = this.lines[this.pos]!;
      if (line.indent !== indent) break;
      if (!line.content.startsWith("-")) break;
      const rest =
        line.content.length === 1 ? "" : line.content.slice(1).replace(/^\s/, "");
      const itemIndent = indent + 2;
      if (rest === "") {
        this.pos++;
        if (this.pos < this.lines.length) {
          const next = this.lines[this.pos]!;
          if (next.indent > indent) {
            result.push(this.parseValueAt(next.indent));
            continue;
          }
        }
        result.push(null);
        continue;
      }
      this.lines[this.pos] = { indent: itemIndent, content: rest };
      if (KEY_HEAD_RE.test(rest)) {
        result.push(this.parseMapping(itemIndent));
      } else {
        this.pos++;
        result.push(parseScalar(rest));
      }
    }
    return result;
  }
}

function sha256Hex(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

interface Heading {
  index: number;
  level: number;
  title: string;
}

function collectHeadings(lines: string[]): Heading[] {
  const out: Heading[] = [];
  for (let i = 0; i < lines.length; i++) {
    const m = HEADING_RE.exec(lines[i]!);
    if (m) out.push({ index: i, level: m[1]!.length, title: m[2]! });
  }
  return out;
}

function sectionEnd(headings: Heading[], from: Heading, totalLines: number): number {
  const next = headings.find(
    (h) => h.index > from.index && h.level <= from.level,
  );
  return next ? next.index : totalLines;
}

function parsePrescriptiveBlocks(
  lines: string[],
  start: number,
  end: number,
): PrescriptiveBlock[] {
  const blocks: PrescriptiveBlock[] = [];
  let i = start;
  while (i < end) {
    const open = /^```(\S*)(?:\s+id=(\S+))?\s*$/.exec(lines[i]!);
    if (!open) {
      i++;
      continue;
    }
    const language = open[1] ?? "";
    const id = open[2];
    const bodyLines: string[] = [];
    i++;
    while (i < end && !/^```\s*$/.test(lines[i]!)) {
      bodyLines.push(lines[i]!);
      i++;
    }
    const body =
      bodyLines.length > 0 ? bodyLines.join("\n") + "\n" : "";
    if (id) {
      blocks.push({ id, language, body, sha256: sha256Hex(body) });
    }
    i++;
  }
  return blocks;
}

export function parseDesignDeterministic(
  source: string,
  sourcePath: string,
): DeterministicResult<DesignDeterministicOutput> {
  const lines = source.split("\n");
  const headings = collectHeadings(lines);

  const invHeading = headings.find((h) => h.title === "Cross-Path Invariants");
  if (!invHeading) {
    return {
      kind: "incomplete",
      reason: "missing_required_heading",
      details: "Cross-Path Invariants",
    };
  }

  const invEnd = sectionEnd(headings, invHeading, lines.length);
  const invBody = lines.slice(invHeading.index + 1, invEnd).join("\n");

  let invariants: unknown[] = [];
  try {
    const parser = new BlockParser(invBody);
    const first = parser.lines[0];
    if (first) {
      const baseIndent = first.indent;
      const value = parser.parseValueAt(baseIndent);
      invariants = Array.isArray(value) ? value : [];
    }
  } catch (err) {
    return {
      kind: "incomplete",
      reason: "unparseable_check_block",
      details: err instanceof Error ? err.message : String(err),
    };
  }

  const snipHeading = headings.find((h) => h.title === "Prescriptive Snippets");
  const prescriptive_blocks: PrescriptiveBlock[] = snipHeading
    ? parsePrescriptiveBlocks(
        lines,
        snipHeading.index + 1,
        sectionEnd(headings, snipHeading, lines.length),
      )
    : [];

  return {
    kind: "ok",
    value: {
      schema: "waygent.design_contract.v1",
      source_path: sourcePath,
      invariants,
      prescriptive_blocks,
      parser: "deterministic",
      extraction_confidence: "high",
    },
  };
}

const TASK_HEADING_RE = /^Task\s+(.+)$/;

function normalizeFileClaim(value: unknown): unknown {
  if (typeof value !== "string") return value;
  return value.replace(/:\s+/, ":");
}

export function parsePlanDeterministic(
  source: string,
  sourcePath: string,
): DeterministicResult<PlanDeterministicOutput> {
  const lines = source.split("\n");
  const headings = collectHeadings(lines);

  const taskHeadings = headings.filter(
    (h) => h.level === 2 && TASK_HEADING_RE.test(h.title),
  );
  if (taskHeadings.length === 0) {
    return {
      kind: "incomplete",
      reason: "missing_required_heading",
      details: "Task",
    };
  }

  const tasks: unknown[] = [];
  for (const heading of taskHeadings) {
    const idMatch = TASK_HEADING_RE.exec(heading.title);
    if (!idMatch) continue;
    const id = idMatch[1]!.trim();
    const end = sectionEnd(headings, heading, lines.length);
    const body = lines.slice(heading.index + 1, end).join("\n");
    const parser = new BlockParser(body);
    const first = parser.lines[0];
    const items: Record<string, unknown>[] = [];
    if (first) {
      const parsed = parser.parseValueAt(first.indent);
      if (Array.isArray(parsed)) {
        for (const item of parsed) {
          if (item && typeof item === "object" && !Array.isArray(item)) {
            items.push(item as Record<string, unknown>);
          }
        }
      }
    }
    const task: Record<string, unknown> = { id };
    for (const item of items) {
      for (const [k, v] of Object.entries(item)) {
        if (k === "file_claims" && Array.isArray(v)) {
          task[k] = v.map(normalizeFileClaim);
        } else {
          task[k] = v;
        }
      }
    }
    tasks.push(task);
  }

  return {
    kind: "ok",
    value: {
      schema: "waygent.plan_contract.v1",
      source_path: sourcePath,
      tasks,
      parser: "deterministic",
      extraction_confidence: "high",
    },
  };
}
