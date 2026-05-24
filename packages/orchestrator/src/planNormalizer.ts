import type { RiskLevel } from "@waygent/contracts";
import type { FileClaim } from "@waygent/runway-control";
import { hasWaygentTaskBlock } from "./planParser";
import { scaffoldWaygentTask } from "./planScaffold";
import { extractInstructionLines } from "./planAdapters/instructionsExtract";
import {
  extractSuperpowersPlan,
  type ExtractedCommandCandidate,
  type ExtractedPlanTask
} from "./planAdapters/planClaimExtraction";
import {
  buildProjectScriptCatalog,
  type ProjectScriptCatalog
} from "./planAdapters/projectScriptCatalog";
import { inferRiskLevel } from "./planAdapters/riskInference";
import {
  classifyVerificationCommand,
  isSafeVerificationCommand
} from "./planAdapters/verificationPolicy";
import { verificationClaimCoverageErrors } from "./planAdapters/verificationCoverage";
import { detectVerifyTheater } from "./planAdapters/verifyQuality";
import type { VerificationExpectedExit } from "./verification";

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

interface NormalizedTaskInput {
  id: string;
  title: string;
  dependencies: string[];
  file_claims: FileClaim[];
  risk: RiskLevel;
  verify: string[];
  verify_fail: string[];
  instructions: string[];
}

interface VerificationPlanCommand {
  command: string;
  expected_exit: VerificationExpectedExit;
}

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

  const extracted = extractSuperpowersPlan(input.markdown);
  if (extracted.tasks.length === 0) {
    return {
      markdown: input.markdown,
      path: input.path,
      mode: "native",
      task_count: 0,
      diagnostics: []
    };
  }

  const catalog = input.workspace ? buildProjectScriptCatalog(input.workspace) : null;
  const workspace = input.workspace ?? "";
  const unsafeVerification = input.unsafe_verification === true;
  const useInferredRisk = input.infer_risk === true;
  const errors: string[] = [];
  const diagnostics: string[] = [];
  const tasks: NormalizedTaskInput[] = [];

  for (const section of extracted.tasks) {
    const commandCandidates = verificationCommandCandidates(section);
    const classifications = commandCandidates.map(({ command }) =>
      classifyVerificationCommand({ command, workspace, catalog })
    );
    for (const classification of classifications) {
      if (classification.status !== "unsafe") continue;
      const unsafeSegment = classification.segments.find((segment) => segment.status === "unsafe")?.command ?? classification.command;
      if (blocksSuperpowersNormalization(classification)) {
        errors.push(`Task ${section.number} "${section.title}" has unsafe verification command: ${unsafeSegment}`);
      } else {
        diagnostics.push(`Task ${section.number} "${section.title}" ignored non-verification command: ${unsafeSegment}`);
      }
    }
    const verificationSpecs = safeVerificationCommands(commandCandidates, workspace, catalog);
    const verify = verificationSpecs.filter((spec) => spec.expected_exit === "zero").map((spec) => spec.command);
    const verifyFail = verificationSpecs.filter((spec) => spec.expected_exit === "nonzero").map((spec) => spec.command);
    const verifyCommands = verificationSpecs.map((spec) => spec.command);
    const fileClaims = fileClaimsFor(section, verifyCommands);
    if (fileClaims.length === 0) {
      const message = `Task ${section.number} "${section.title}" is missing recoverable file claims`;
      (unsafeVerification ? diagnostics : errors).push(message);
    }
    if (verificationSpecs.length === 0) {
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

    const theater = detectVerifyTheater({ verify: verifyCommands, file_claims: fileClaims });
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
      verify_fail: verifyFail,
      instructions: extractInstructionLines(section.body)
    });
  }

  const coverageErrors = verificationClaimCoverageErrors(tasks.map((task) => ({
    title: task.title,
    label: `Task ${task.id.replace(/^task_(\d+)_.*$/, "$1")} "${task.title}"`,
    file_claims: task.file_claims,
    verification_commands: [...task.verify, ...task.verify_fail]
  })));
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

export function isNormalizableSuperpowersPlan(markdown: string, workspace?: string): boolean {
  if (hasWaygentTaskBlock(markdown)) return true;
  const extracted = extractSuperpowersPlan(markdown);
  if (extracted.tasks.length === 0) return false;
  const catalog = workspace ? buildProjectScriptCatalog(workspace) : null;
  const ws = workspace ?? "";
  return extracted.tasks.some(
    (task: ExtractedPlanTask) =>
      safeVerificationCommands(verificationCommandCandidates(task), ws, catalog).length > 0 &&
      fileClaimsFor(task, safeVerificationCommands(verificationCommandCandidates(task), ws, catalog).map((spec) => spec.command)).length > 0
  );
}

function fileClaimsFor(section: ExtractedPlanTask, verify: ReadonlyArray<string> = []): FileClaim[] {
  if (section.explicit_file_claims.length > 0) return section.explicit_file_claims;
  if (section.prose_file_claims.length > 0) return section.prose_file_claims;
  if (isClaimlessVerificationTask(section, verify)) return [{ path: ".", mode: "read_only" }];
  return [];
}

function isClaimlessVerificationTask(section: ExtractedPlanTask, verify: ReadonlyArray<string>): boolean {
  if (verify.length === 0) return false;
  if (/^(final\s+)?verification$/i.test(section.title.trim())) return true;
  return /\bno source edits\b/i.test(section.body);
}

function blocksSuperpowersNormalization(
  classification: ReturnType<typeof classifyVerificationCommand>
): boolean {
  return classification.segments.some((segment) =>
    segment.reason === "destructive" ||
    segment.reason === "workspace_escape" ||
    /[|;`]/.test(segment.command) ||
    /\s[12]?>/.test(segment.command)
  );
}

function safeVerificationCommands(
  commands: ReadonlyArray<VerificationPlanCommand>,
  workspace: string,
  catalog: ProjectScriptCatalog | null
): VerificationPlanCommand[] {
  const safe = commands.filter(({ command }) => isSafeVerificationCommand({ command, workspace, catalog }));
  const finalExpected = safe.some((spec) => spec.expected_exit === "zero") ? "zero" : "nonzero";
  const seen = new Set<string>();
  const out: VerificationPlanCommand[] = [];
  for (const spec of safe) {
    if (spec.expected_exit !== finalExpected || seen.has(spec.command)) continue;
    seen.add(spec.command);
    out.push(spec);
  }
  return out;
}

function verificationCommandCandidates(section: ExtractedPlanTask): VerificationPlanCommand[] {
  const candidates = section.command_candidates?.length
    ? section.command_candidates
    : section.fenced_commands.map((command) => ({ command, line_end: section.line_start } as ExtractedCommandCandidate));
  return candidates.map((candidate) => ({
    command: candidate.command,
    expected_exit: expectedExitForCandidate(section, candidate)
  }));
}

function expectedExitForCandidate(section: ExtractedPlanTask, candidate: Pick<ExtractedCommandCandidate, "line_end">): VerificationExpectedExit {
  const lines = section.body.split(/\r?\n/);
  const relativeEndLine = Math.max(0, candidate.line_end - section.line_start);
  for (let index = relativeEndLine + 1; index < lines.length; index += 1) {
    const line = (lines[index] ?? "").trim();
    if (!line) continue;
    if (/^#{2,6}\s+/.test(line) || /^-\s+\[[ xX]\]\s+/.test(line)) break;
    const expected = line.match(/^Expected:\s*(.*)$/i);
    if (!expected) continue;
    return /\b(FAIL|RED|fail|failed|failing|실패)\b/i.test(expected[1] ?? "")
      ? "nonzero"
      : "zero";
  }
  return "zero";
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
// Re-export classification helpers so callers can inspect verification policy.
export { classifyVerificationCommand, isSafeVerificationCommand };
