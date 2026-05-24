import type { RiskLevel } from "@waygent/contracts";
import type { FileClaim } from "@waygent/runway-control";
import { hasWaygentTaskBlock } from "./planParser";
import { scaffoldWaygentTask } from "./planScaffold";
import { extractInstructionLines } from "./planAdapters/instructionsExtract";
import {
  extractSuperpowersPlan,
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
  instructions: string[];
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
    const fileClaims = section.explicit_file_claims;
    const classifications = section.fenced_commands.map((command) =>
      classifyVerificationCommand({ command, workspace, catalog })
    );
    for (const classification of classifications) {
      if (classification.status !== "unsafe") continue;
      const unsafeSegment = classification.segments.find((segment) => segment.status === "unsafe")?.command ?? classification.command;
      errors.push(`Task ${section.number} "${section.title}" has unsafe verification command: ${unsafeSegment}`);
    }
    const verify = safeVerificationCommands(section.fenced_commands, workspace, catalog);
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

  const coverageErrors = verificationClaimCoverageErrors(tasks.map((task) => ({
    title: task.title,
    label: `Task ${task.id.replace(/^task_(\d+)_.*$/, "$1")} "${task.title}"`,
    file_claims: task.file_claims,
    verification_commands: task.verify
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
      task.explicit_file_claims.length > 0 &&
      safeVerificationCommands(task.fenced_commands, ws, catalog).length > 0
  );
}

function safeVerificationCommands(
  commands: ReadonlyArray<string>,
  workspace: string,
  catalog: ProjectScriptCatalog | null
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const command of commands) {
    if (seen.has(command)) continue;
    if (isSafeVerificationCommand({ command, workspace, catalog })) {
      seen.add(command);
      out.push(command);
    }
  }
  return out;
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
