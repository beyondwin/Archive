import type { ParserSource } from "./types";
import { parseDesignSource, parsePlanSource, type ParseOptions } from "./parse";

export interface LintResult {
  parser: ParserSource | "failed";
  report: string;
}

function pickString(value: unknown, key: string, fallback = ""): string {
  if (typeof value !== "object" || value === null) return fallback;
  const v = (value as Record<string, unknown>)[key];
  return typeof v === "string" ? v : fallback;
}

function pickArray(value: unknown, key: string): unknown[] {
  if (typeof value !== "object" || value === null) return [];
  const v = (value as Record<string, unknown>)[key];
  return Array.isArray(v) ? v : [];
}

function pickBool(value: unknown, key: string): boolean {
  if (typeof value !== "object" || value === null) return false;
  return (value as Record<string, unknown>)[key] === true;
}

export async function lintDesign(
  markdown: string,
  sourcePath: string,
  options: ParseOptions
): Promise<LintResult> {
  const out = await parseDesignSource(markdown, sourcePath, options);
  if (out.kind !== "ok") {
    const reason = out.kind === "failed" ? out.reason : out.kind === "incomplete" ? out.reason : "";
    return { parser: "failed", report: `FAILED to extract design (${out.kind}): ${reason}` };
  }
  const lines: string[] = [];
  lines.push(`source: ${sourcePath}`);
  lines.push(`parser: ${out.value.parser}`);
  lines.push(`extraction_confidence: ${out.value.extraction_confidence}`);
  lines.push(`invariants: ${out.value.invariants.length}`);
  for (const inv of out.value.invariants) {
    const id = pickString(inv, "id", "(no id)");
    const pathsBound = pickArray(inv, "paths_bound")
      .map((p) => (typeof p === "string" ? p : JSON.stringify(p)))
      .join(", ");
    const ack = pickBool(inv, "policy_ack_required");
    lines.push(`  - ${id} (paths: ${pathsBound}) ack_required=${ack}`);
  }
  lines.push(`prescriptive_blocks: ${out.value.prescriptive_blocks.length}`);
  for (const b of out.value.prescriptive_blocks) {
    lines.push(`  - ${b.id} (${b.language}, ${b.sha256.slice(0, 12)})`);
  }
  return { parser: out.value.parser, report: lines.join("\n") };
}

export async function lintPlan(
  markdown: string,
  sourcePath: string,
  options: ParseOptions
): Promise<LintResult> {
  const out = await parsePlanSource(markdown, sourcePath, options);
  if (out.kind !== "ok") {
    const reason = out.kind === "failed" ? out.reason : out.kind === "incomplete" ? out.reason : "";
    return { parser: "failed", report: `FAILED to extract plan (${out.kind}): ${reason}` };
  }
  const lines: string[] = [];
  lines.push(`source: ${sourcePath}`);
  lines.push(`parser: ${out.value.parser}`);
  lines.push(`tasks: ${out.value.tasks.length}`);
  for (const t of out.value.tasks) {
    const id = pickString(t, "id", "(no id)");
    const risk = pickString(t, "risk", "?");
    const claims = pickArray(t, "file_claims")
      .map((c) => (typeof c === "string" ? c : JSON.stringify(c)))
      .join(",");
    lines.push(`  - ${id} risk=${risk} claims=[${claims}]`);
  }
  return { parser: out.value.parser, report: lines.join("\n") };
}
