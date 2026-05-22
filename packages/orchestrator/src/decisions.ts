import { renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { DecisionEntry, WaygentRunStateV2, WorkerResult } from "@waygent/contracts";

export function appendDecisionFromWorker(
  state: Pick<WaygentRunStateV2, "decisions_register">,
  worker: Pick<WorkerResult, "task_id" | "changed_files" | "evidence">
): DecisionEntry | null {
  const rawDecision = worker.evidence.key_decision;
  if (typeof rawDecision !== "string" || isEmptyDecision(rawDecision)) return null;
  const supersedes = typeof worker.evidence.supersedes === "string" && worker.evidence.supersedes.trim().length > 0
    ? worker.evidence.supersedes.trim()
    : null;
  const entry: DecisionEntry = {
    decision_id: `decision_${worker.task_id}_${(state.decisions_register ?? []).length + 1}`,
    task_id: worker.task_id,
    decision: rawDecision.trim(),
    files: worker.changed_files,
    made_at: new Date().toISOString(),
    supersedes
  };
  state.decisions_register = [...(state.decisions_register ?? []).filter((item) => item.decision_id !== supersedes), entry];
  return entry;
}

export function packetDecisionSummaries(state: Pick<WaygentRunStateV2, "decisions_register">): Array<{ decision_id: string; summary: string }> {
  return (state.decisions_register ?? []).map((entry) => ({
    decision_id: entry.decision_id,
    summary: entry.decision
  }));
}

export function renderDecisionsMarkdown(runId: string, decisions: DecisionEntry[]): string {
  if (decisions.length === 0) {
    return [`# Waygent Decisions`, "", `Run: ${runId}`, "", "No runtime decisions recorded.", ""].join("\n");
  }
  return [
    "# Waygent Decisions",
    "",
    `Run: ${runId}`,
    "",
    ...decisions.map((entry) => [
      `## ${entry.decision_id}`,
      "",
      `- Task: ${entry.task_id}`,
      `- Made at: ${entry.made_at}`,
      `- Supersedes: ${entry.supersedes ?? "(none)"}`,
      `- Files: ${entry.files.length > 0 ? entry.files.join(", ") : "(none)"}`,
      "",
      entry.decision,
      ""
    ].join("\n"))
  ].join("\n");
}

export function writeDecisionsProjection(runRoot: string, runId: string, decisions: DecisionEntry[]): string {
  const target = join(runRoot, "DECISIONS.md");
  const temp = `${target}.tmp`;
  writeFileSync(temp, renderDecisionsMarkdown(runId, decisions));
  renameSync(temp, target);
  return target;
}

function isEmptyDecision(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  return normalized.length === 0 || normalized === "(none)" || normalized === "none" || normalized === "n/a";
}
