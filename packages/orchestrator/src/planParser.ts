import type { RiskLevel } from "@waygent/contracts";
import type { FileClaim, FileClaimMode } from "@waygent/runway-control";
import { extractInstructionLines } from "./planAdapters/instructionsExtract";

export type VerifyIsolation = "isolated" | "fast" | "auto";

export interface ParsedWaygentTask {
  id: string;
  title: string;
  dependencies: string[];
  file_claims: FileClaim[];
  risk: RiskLevel;
  verification_commands: string[];
  instructions: string[];
  verify_isolation?: VerifyIsolation;
}

export interface ParsedWaygentPlan {
  tasks: ParsedWaygentTask[];
}

export interface ParseWaygentPlanOptions {
  inherit_plan_prose?: boolean;
}

const TASK_BLOCK = /```yaml\s+waygent-task\r?\n([\s\S]*?)\r?\n```/g;
const TASK_MARKER = /```yaml\s+waygent-task\r?\n/;
const TASK_HEADING = /^(#{2,3})\s+Task\s+\d+\s*[:.]/gm;
const VALID_RISK = new Set<RiskLevel>(["low", "medium", "high"]);
const VALID_CLAIM_MODE = new Set<FileClaimMode>(["owned", "shared_append", "read_only"]);

export function parseWaygentPlan(markdown: string, options?: ParseWaygentPlanOptions): ParsedWaygentPlan {
  const inheritProse = options?.inherit_plan_prose !== false;
  const headings: Array<{ index: number }> = [];
  for (const match of markdown.matchAll(TASK_HEADING)) {
    if (match.index !== undefined) headings.push({ index: match.index + match[0].length });
  }

  const tasks: ParsedWaygentTask[] = [];
  let lastBlockEnd = 0;
  for (const match of markdown.matchAll(TASK_BLOCK)) {
    if (match.index === undefined) continue;
    const blockStart = match.index;
    const yamlBody = match[1] ?? "";
    const task = parseTaskBlock(yamlBody);

    if (inheritProse && task.instructions.length === 0) {
      const headingBefore = [...headings]
        .reverse()
        .find((h) => h.index > lastBlockEnd && h.index < blockStart);
      if (headingBefore) {
        const proseSlice = markdown.slice(headingBefore.index, blockStart);
        task.instructions = extractInstructionLines(proseSlice);
      }
    }

    tasks.push(task);
    lastBlockEnd = blockStart + match[0].length;
  }
  if (tasks.length === 0) {
    throw new Error(missingWaygentTaskBlockMessage(markdown));
  }
  return { tasks };
}

export function hasWaygentTaskBlock(markdown: string): boolean {
  return TASK_MARKER.test(markdown);
}

function parseTaskBlock(block: string): ParsedWaygentTask {
  const lines = block.split("\n").map((line) => line.trimEnd());
  const scalar = new Map<string, string>();
  const fileClaims: FileClaim[] = [];
  const verification: string[] = [];
  const instructions: string[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]?.trim();
    if (!line) continue;
    if (line === "dependencies:") {
      const deps: string[] = [];
      index = readStringList(lines, index + 1, deps) - 1;
      scalar.set("dependencies", `[${deps.join(", ")}]`);
      continue;
    }
    if (line.startsWith("dependencies:")) {
      const value = line.slice("dependencies:".length).trim();
      if (value === "") {
        const deps: string[] = [];
        index = readStringList(lines, index + 1, deps) - 1;
        scalar.set("dependencies", `[${deps.join(", ")}]`);
      } else if (value.startsWith("[")) {
        scalar.set("dependencies", value);
      } else {
        scalar.set("dependencies", `[${value}]`);
      }
      continue;
    }
    const scalarMatch = line.match(/^([a-z_]+):\s*(.*)$/);
    const key = scalarMatch?.[1];
    if (key && key !== "file_claims" && key !== "verify" && key !== "acceptance_commands" && key !== "instructions") {
      scalar.set(key, scalarMatch[2] ?? "");
      continue;
    }
    if (line === "file_claims:") {
      index = readFileClaims(lines, index + 1, fileClaims) - 1;
      continue;
    }
    if (line === "verify:") {
      index = readStringList(lines, index + 1, verification) - 1;
      continue;
    }
    if (line === "acceptance_commands:") {
      index = readStringList(lines, index + 1, verification) - 1;
      continue;
    }
    if (line === "instructions:") {
      index = readStringList(lines, index + 1, instructions) - 1;
    }
  }

  if (!scalar.has("id") && scalar.has("task_id")) {
    scalar.set("id", scalar.get("task_id")!);
  }

  const missing = ["id", "title", "dependencies", "risk"].filter((key) => !scalar.has(key));
  if (missing.length > 0) {
    throw new Error(`missing required waygent-task fields: ${missing.join(", ")}`);
  }

  const risk = scalar.get("risk") as RiskLevel;
  if (!VALID_RISK.has(risk)) {
    throw new Error(`invalid risk ${risk}`);
  }

  const verifyIsolationRaw = scalar.get("verify_isolation");
  let verifyIsolation: VerifyIsolation | undefined;
  if (typeof verifyIsolationRaw === "string") {
    const value = cleanScalar(verifyIsolationRaw);
    if (value === "isolated" || value === "fast" || value === "auto") {
      verifyIsolation = value;
    }
  }

  return {
    id: scalar.get("id")!,
    title: scalar.get("title")!,
    dependencies: parseInlineList(scalar.get("dependencies")!),
    file_claims: fileClaims,
    risk,
    verification_commands: verification,
    instructions,
    ...(verifyIsolation ? { verify_isolation: verifyIsolation } : {})
  };
}

function readFileClaims(lines: string[], start: number, out: FileClaim[]): number {
  let current: Partial<FileClaim> | null = null;
  let index = start;
  for (; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    if (!line.startsWith("  - ") && !line.startsWith("    ")) break;
    const trimmed = line.trim();
    if (trimmed.startsWith("- {")) {
      if (current) pushClaim(current, out);
      pushClaim(parseInlineClaim(trimmed), out);
      current = null;
    } else if (trimmed.startsWith("- path:")) {
      if (current) pushClaim(current, out);
      current = { path: cleanScalar(trimmed.slice("- path:".length).trim()) };
    } else if (trimmed.startsWith("mode:")) {
      current = current ?? {};
      current.mode = cleanScalar(trimmed.slice("mode:".length).trim()) as FileClaimMode;
    }
  }
  if (current) pushClaim(current, out);
  return index;
}

function parseInlineClaim(line: string): Partial<FileClaim> {
  const body = line.replace(/^- \{/, "").replace(/\}$/, "");
  const claim: Partial<FileClaim> = {};
  for (const part of body.split(",")) {
    const [rawKey, ...rawValue] = part.split(":");
    const key = rawKey?.trim();
    const value = cleanScalar(rawValue.join(":").trim());
    if (key === "path") claim.path = value;
    if (key === "mode") claim.mode = value as FileClaimMode;
  }
  return claim;
}

function cleanScalar(value: string): string {
  const trimmed = value.trim();
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function pushClaim(claim: Partial<FileClaim>, out: FileClaim[]): void {
  if (!claim.path || !claim.mode) throw new Error("file_claims entries require path and mode");
  const mode = normalizeClaimMode(claim.mode);
  if (!VALID_CLAIM_MODE.has(mode)) throw new Error(`invalid file claim mode ${claim.mode}`);
  out.push({ path: claim.path, mode });
}

function normalizeClaimMode(mode: FileClaimMode | string): FileClaimMode {
  if (mode === "edit") return "owned";
  return mode as FileClaimMode;
}

function readStringList(lines: string[], start: number, out: string[]): number {
  let index = start;
  for (; index < lines.length; index += 1) {
    const trimmed = lines[index]?.trim() ?? "";
    if (!trimmed.startsWith("- ")) break;
    out.push(trimmed.slice(2).trim());
  }
  return index;
}

function parseInlineList(value: string): string[] {
  const trimmed = value.trim();
  if (trimmed === "[]") return [];
  if (!trimmed.startsWith("[") || !trimmed.endsWith("]")) {
    throw new Error(`expected inline list, got ${value}`);
  }
  return trimmed
    .slice(1, -1)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function missingWaygentTaskBlockMessage(markdown: string): string {
  const looksLikeImplementationPlan =
    /^# .*Implementation Plan/im.test(markdown) ||
    /^#{2,3}\s+Task\s+\d+/im.test(markdown) ||
    /\*\*Files:\*\*/im.test(markdown) ||
    /-\s+(Create|Modify):\s+`[^`]+`/im.test(markdown);
  const prefix = looksLikeImplementationPlan
    ? "missing waygent-task block: this looks like a human implementation plan, not an executable Waygent plan."
    : "missing waygent-task block: input is not an executable Waygent plan.";
  return [
    prefix,
    "Add one or more fenced ```yaml waygent-task blocks with id, title, dependencies, file_claims, risk, and verify fields.",
    "For a safe scaffold, run waygent scaffold-plan --id <task_id> --title <title> --claim <path:mode> --risk <low|medium|high> --verify <command>.",
    "Waygent will not infer file claims, risk, or verification commands from prose."
  ].join(" ");
}
