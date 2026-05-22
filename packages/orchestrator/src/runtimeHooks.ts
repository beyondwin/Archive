import type { WaygentFileClaim, WorkerResult } from "@waygent/contracts";

export interface RuntimeHookInput {
  enabled: boolean;
  task_id: string;
  commands: string[];
  file_claims: WaygentFileClaim[];
}

export interface FinalOutputHookInput {
  enabled: boolean;
  task_id: string;
  worker: unknown;
  stdout: string;
  stderr: string;
}

export interface HookDenial {
  hook_id: string;
  reason: string;
  evidence: Record<string, unknown>;
}

export interface HookEvaluation {
  status: "passed" | "denied" | "bypassed";
  denials: HookDenial[];
}

const DANGEROUS_COMMAND = /\b(rm\s+-rf|git\s+reset\s+--hard|git\s+clean\s+-fd|sudo\s+|chmod\s+777|curl\s+[^|;]+[|]\s*sh|wget\s+[^|;]+[|]\s*sh)\b/;

export function evaluatePreDispatchHooks(input: RuntimeHookInput): HookEvaluation {
  if (!input.enabled) return { status: "bypassed", denials: [] };
  const denials: HookDenial[] = [];
  for (const command of input.commands) {
    if (DANGEROUS_COMMAND.test(command)) {
      denials.push({
        hook_id: "dangerous_command",
        reason: "dangerous command pattern detected before provider dispatch",
        evidence: { task_id: input.task_id, command }
      });
    }
  }
  for (const claim of input.file_claims) {
    if (claim.path.includes(".agentlens/") || claim.path.includes(".codex-orchestrator/") || claim.path.includes(".orchestrator/")) {
      denials.push({
        hook_id: "runtime_state_claim",
        reason: "task attempted to claim runtime state path",
        evidence: { task_id: input.task_id, path: claim.path }
      });
    }
  }
  return { status: denials.length > 0 ? "denied" : "passed", denials };
}

export function evaluateFinalOutputHooks(input: FinalOutputHookInput): HookEvaluation {
  if (!input.enabled) return { status: "bypassed", denials: [] };
  const denials: HookDenial[] = [];
  const shapeValid = isWorkerResultShape(input.worker);
  if (!shapeValid) {
    denials.push({
      hook_id: "worker_result_shape",
      reason: "provider final output is not a runway.worker_result.v1 object",
      evidence: { task_id: input.task_id }
    });
  }
  // When the worker_result shape is valid, only scan executable fields and
  // stderr — never the free-text summary or wrapping provider stdout, which
  // legitimately quote destructive command names as descriptive prose.
  // When the shape is invalid we have no structured surface, so fall back to
  // the blunt stdout+stderr scan as defense in depth.
  const scanTargets: string[] = shapeValid
    ? [...workerExecutableStrings(input.worker), input.stderr]
    : [input.stdout, input.stderr];
  const offending = scanTargets.find((target) => typeof target === "string" && DANGEROUS_COMMAND.test(target));
  if (offending !== undefined) {
    denials.push({
      hook_id: "dangerous_output_command",
      reason: "provider output contains a dangerous command pattern",
      evidence: { task_id: input.task_id }
    });
  }
  return { status: denials.length > 0 ? "denied" : "passed", denials };
}

function workerExecutableStrings(worker: unknown): string[] {
  if (!worker || typeof worker !== "object") return [];
  const evidence = (worker as { evidence?: unknown }).evidence;
  if (!evidence || typeof evidence !== "object") return [];
  const verification = (evidence as { verification_commands?: unknown }).verification_commands;
  if (!Array.isArray(verification)) return [];
  return verification.filter((item): item is string => typeof item === "string");
}

export function debugArtifactDenials(taskId: string, changedFiles: string[], allowDebugArtifacts = false): HookDenial[] {
  if (allowDebugArtifacts) return [];
  return changedFiles
    .filter((file) => /(^|\/)(debug|tmp|scratch|transcript|full[-_]?log)/i.test(file))
    .map((file) => ({
      hook_id: "debug_artifact",
      reason: "debug artifact path cannot be sealed into a checkpoint without allowlisting",
      evidence: { task_id: taskId, file }
    }));
}

function isWorkerResultShape(value: unknown): value is WorkerResult {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Partial<WorkerResult>;
  return record.schema === "runway.worker_result.v1" &&
    typeof record.task_id === "string" &&
    typeof record.candidate_id === "string" &&
    (record.status === "completed" || record.status === "failed" || record.status === "blocked") &&
    Array.isArray(record.changed_files) &&
    typeof record.summary === "string" &&
    Boolean(record.evidence) &&
    typeof record.evidence === "object";
}
