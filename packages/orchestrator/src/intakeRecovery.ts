import type {
  IntakeFinding,
  IntakeRepairAction,
  WaygentIntakeRecovery
} from "@waygent/contracts";
import type { FileClaim, FileClaimMode } from "@waygent/runway-control";
import {
  normalizeWaygentPlanInput,
  type NormalizedWaygentPlan
} from "./planNormalizer";
import { scaffoldWaygentTask } from "./planScaffold";

export interface RecoverWaygentPlanInput {
  markdown: string;
  path: string | null;
  workspace: string;
  spec_markdown: string;
  spec_path: string | null;
  unsafe_verification?: boolean;
  infer_risk?: boolean;
}

export interface RecoveredWaygentPlan {
  status: WaygentIntakeRecovery["status"];
  normalized_plan: NormalizedWaygentPlan;
  report: WaygentIntakeRecovery;
}

interface LenientTaskSection {
  number: number;
  title: string;
  body: string;
}

const TASK_HEADING = /^#{1,4}\s+(?:Task|작업|Phase)\s+(\d+)\s*[:.)-]?\s*(.*)$/gim;
const INLINE_PATH = /`([^`]+\.(?:ts|tsx|js|jsx|json|md|mdx|toml|yaml|yml|rs|py|sh|css|html))`/g;
const FENCED_COMMAND = /```(?:bash|sh|shell)?\r?\n([\s\S]*?)\r?\n```/gim;
const DESTRUCTIVE_COMMAND = /\b(rm\s+-rf|git\s+reset\s+--hard|git\s+clean\s+-fd|drop\s+table|kubectl\s+delete)\b/i;
const SAFE_VERIFY_PREFIXES = [
  "bun test",
  "bun run check",
  "bun run typecheck",
  "bun run build",
  "bun run waygent:scenarios",
  "bun run waygent:dogfood",
  "cargo test",
  "npm test",
  "npm run test",
  "pnpm test",
  "yarn test",
  "test ",
  "git diff --check",
  "printf "
];

export function recoverWaygentPlanInput(input: RecoverWaygentPlanInput): RecoveredWaygentPlan {
  const startedAt = new Date().toISOString();
  try {
    const normalized = normalizeWaygentPlanInput({
      markdown: input.markdown,
      path: input.path,
      workspace: input.workspace,
      unsafe_verification: input.unsafe_verification,
      infer_risk: input.infer_risk
    });
    return {
      status: "not_needed",
      normalized_plan: normalized,
      report: {
        status: "not_needed",
        started_at: startedAt,
        completed_at: new Date().toISOString(),
        normalized_plan_ref: null,
        recovery_report_ref: null,
        findings: [],
        repair_actions: [],
        can_start: true,
        confidence: "deterministic",
        question: null
      }
    };
  } catch (error) {
    return deterministicRepair(input, startedAt, error instanceof Error ? error.message : String(error));
  }
}

function deterministicRepair(
  input: RecoverWaygentPlanInput,
  startedAt: string,
  strictError: string
): RecoveredWaygentPlan {
  const findings: IntakeFinding[] = [{
    code: "task_body_not_yaml",
    severity: "warning",
    message: strictError,
    task_id: null,
    evidence_refs: planEvidence(input.path)
  }];
  const actions: IntakeRepairAction[] = [];
  const sections = extractLenientTaskSections(input.markdown);
  const tasks = sections.map((section) => recoverSection(section, findings, input.path));
  for (let index = 1; index < tasks.length; index += 1) {
    tasks[index]!.dependencies = [tasks[index - 1]!.id];
  }
  const blocking = findings.filter((finding) => finding.severity === "blocking");
  const canStart = tasks.length > 0 && blocking.length === 0;
  const status: WaygentIntakeRecovery["status"] = canStart ? "recovered" : "decision_required";
  const normalizedMarkdown = canStart
    ? [
      "# Normalized Waygent Plan",
      "",
      `Source: ${input.path || "inline"}`,
      "",
      ...tasks.map((task) => scaffoldWaygentTask(task))
    ].join("\n")
    : input.markdown;

  if (canStart) {
    actions.push({
      action: "deterministic_markdown_intake_repair",
      status: "applied",
      reason: "Recovered executable task blocks from markdown headings, path references, and safe verification commands.",
      evidence_refs: ["artifacts/intake/normalized-plan.md"]
    });
  } else {
    actions.push({
      action: "deterministic_markdown_intake_repair",
      status: "blocked",
      reason: "High-risk ambiguity prevents automatic execution.",
      evidence_refs: planEvidence(input.path)
    });
  }

  const report: WaygentIntakeRecovery = {
    status,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    normalized_plan_ref: canStart ? "artifacts/intake/normalized-plan.md" : null,
    recovery_report_ref: "artifacts/intake/recovery-report.json",
    findings,
    repair_actions: actions,
    can_start: canStart,
    confidence: canStart ? "deterministic" : "blocked",
    question: canStart ? null : questionFor(blocking)
  };

  return {
    status,
    normalized_plan: {
      markdown: normalizedMarkdown,
      path: input.path,
      mode: canStart ? "superpowers" : "native",
      task_count: canStart ? tasks.length : 0,
      diagnostics: findings.map((finding) => `${finding.code}: ${finding.message}`)
    },
    report
  };
}

function recoverSection(section: LenientTaskSection, findings: IntakeFinding[], planPath: string | null) {
  const taskId = `task_${section.number}_${slugify(section.title)}`;
  const evidenceRefs = [...planEvidence(planPath), `plan:task-${section.number}`];
  const fileClaims = extractFileClaims(section.body, findings, taskId, evidenceRefs);
  const verify = extractVerificationCommands(section.body, findings, taskId, evidenceRefs);
  if (DESTRUCTIVE_COMMAND.test(section.body)) {
    findings.push({
      code: "destructive_command_candidate",
      severity: "blocking",
      message: `Task ${section.number} contains a destructive command candidate.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  if (fileClaims.length === 0) {
    findings.push({
      code: "file_claims_in_prose",
      severity: "blocking",
      message: `Task ${section.number} has no recoverable file claim.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  if (verify.length === 0) {
    findings.push({
      code: "missing_verification_for_source_mutation",
      severity: "blocking",
      message: `Task ${section.number} has no safe verification command.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  return {
    id: taskId,
    title: section.title,
    dependencies: [],
    file_claims: fileClaims,
    risk: "high" as const,
    verify,
    instructions: instructionLines(section.body)
  };
}

function extractLenientTaskSections(markdown: string): LenientTaskSection[] {
  const headings = [...markdown.matchAll(TASK_HEADING)];
  return headings.map((match, index) => {
    const start = typeof match.index === "number" ? match.index : 0;
    const nextIndex = index + 1 < headings.length ? headings[index + 1]!.index : undefined;
    const end = typeof nextIndex === "number" ? nextIndex : markdown.length;
    const rawTitle = (match[2] || "").trim();
    return {
      number: Number(match[1]),
      title: rawTitle || `Task ${match[1]}`,
      body: markdown.slice(start, end)
    };
  });
}

function extractFileClaims(body: string, findings: IntakeFinding[], taskId: string, evidenceRefs: string[]): FileClaim[] {
  const claims: FileClaim[] = [];
  for (const match of body.matchAll(INLINE_PATH)) {
    const path = (match[1] || "").trim();
    if (!path || path.includes("..")) continue;
    claims.push({ path, mode: inferClaimMode(body, path) });
  }
  const unique = new Map(claims.map((claim) => [claim.path, claim]));
  if (unique.size > 0) {
    findings.push({
      code: "file_claims_in_prose",
      severity: "warning",
      message: `Recovered ${unique.size} file claim(s) from prose.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  return [...unique.values()];
}

function inferClaimMode(body: string, path: string): FileClaimMode {
  const before = body.slice(Math.max(0, body.indexOf(path) - 80), body.indexOf(path)).toLowerCase();
  if (/\b(read|inspect|review)\b/.test(before)) return "read_only";
  if (/\b(append|add to)\b/.test(before)) return "shared_append";
  return "owned";
}

function extractVerificationCommands(body: string, findings: IntakeFinding[], taskId: string, evidenceRefs: string[]): string[] {
  const commands = [...body.matchAll(FENCED_COMMAND)]
    .flatMap((match) => logicalCommandLines(match[1] || ""))
    .filter((command) => SAFE_VERIFY_PREFIXES.some((prefix) => command === prefix.trim() || command.startsWith(prefix)));
  const unique = [...new Set(commands)];
  if (unique.length > 0) {
    findings.push({
      code: "verification_command_in_prose",
      severity: "warning",
      message: `Recovered ${unique.length} verification command(s) from prose.`,
      task_id: taskId,
      evidence_refs: evidenceRefs
    });
  }
  return unique;
}

function logicalCommandLines(raw: string): string[] {
  return raw.split(/\r?\n/).map((line) => line.trim()).filter((line) => line && !line.startsWith("#"));
}

function instructionLines(body: string): string[] {
  return body.split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("```") && !line.startsWith("#"))
    .slice(0, 20);
}

function questionFor(blocking: IntakeFinding[]): string {
  if (blocking.some((finding) => finding.code === "destructive_command_candidate")) {
    return "The plan contains a destructive command candidate. Confirm the intended safe replacement before execution.";
  }
  return "Waygent could not recover a safe executable plan. Provide explicit file claims and verification commands.";
}

function planEvidence(path: string | null): string[] {
  return [path ? `plan:${path}` : "plan:inline"];
}

function slugify(title: string): string {
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return slug || "task";
}
