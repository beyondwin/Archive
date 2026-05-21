import type { RiskLevel } from "@waygent/contracts";
import type { FileClaim, FileClaimMode } from "@waygent/runway-control";

export interface ParsedWaygentTask {
  id: string;
  title: string;
  dependencies: string[];
  file_claims: FileClaim[];
  risk: RiskLevel;
  verification_commands: string[];
}

export interface ParsedWaygentPlan {
  tasks: ParsedWaygentTask[];
}

const TASK_BLOCK = /```yaml waygent-task\n([\s\S]*?)\n```/g;
const VALID_RISK = new Set<RiskLevel>(["low", "medium", "high"]);
const VALID_CLAIM_MODE = new Set<FileClaimMode>(["owned", "shared_append", "read_only"]);

export function parseWaygentPlan(markdown: string): ParsedWaygentPlan {
  const tasks = [...markdown.matchAll(TASK_BLOCK)].map((match) => parseTaskBlock(match[1] ?? ""));
  if (tasks.length === 0) {
    throw new Error("missing waygent-task block");
  }
  return { tasks };
}

function parseTaskBlock(block: string): ParsedWaygentTask {
  const lines = block.split("\n").map((line) => line.trimEnd());
  const scalar = new Map<string, string>();
  const fileClaims: FileClaim[] = [];
  const verification: string[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]?.trim();
    if (!line) continue;
    const scalarMatch = line.match(/^([a-z_]+):\s*(.*)$/);
    const key = scalarMatch?.[1];
    if (key && key !== "file_claims" && key !== "verify") {
      scalar.set(key, scalarMatch[2] ?? "");
      continue;
    }
    if (line === "file_claims:") {
      index = readFileClaims(lines, index + 1, fileClaims) - 1;
      continue;
    }
    if (line === "verify:") {
      index = readStringList(lines, index + 1, verification) - 1;
    }
  }

  const missing = ["id", "title", "dependencies", "risk"].filter((key) => !scalar.has(key));
  if (missing.length > 0) {
    throw new Error(`missing required waygent-task fields: ${missing.join(", ")}`);
  }

  const risk = scalar.get("risk") as RiskLevel;
  if (!VALID_RISK.has(risk)) {
    throw new Error(`invalid risk ${risk}`);
  }

  return {
    id: scalar.get("id")!,
    title: scalar.get("title")!,
    dependencies: parseInlineList(scalar.get("dependencies")!),
    file_claims: fileClaims,
    risk,
    verification_commands: verification
  };
}

function readFileClaims(lines: string[], start: number, out: FileClaim[]): number {
  let current: Partial<FileClaim> | null = null;
  let index = start;
  for (; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    if (!line.startsWith("  - ") && !line.startsWith("    ")) break;
    const trimmed = line.trim();
    if (trimmed.startsWith("- path:")) {
      if (current) pushClaim(current, out);
      current = { path: trimmed.slice("- path:".length).trim() };
    } else if (trimmed.startsWith("mode:")) {
      current = current ?? {};
      current.mode = trimmed.slice("mode:".length).trim() as FileClaimMode;
    }
  }
  if (current) pushClaim(current, out);
  return index;
}

function pushClaim(claim: Partial<FileClaim>, out: FileClaim[]): void {
  if (!claim.path || !claim.mode) throw new Error("file_claims entries require path and mode");
  if (!VALID_CLAIM_MODE.has(claim.mode)) throw new Error(`invalid file claim mode ${claim.mode}`);
  out.push({ path: claim.path, mode: claim.mode });
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
