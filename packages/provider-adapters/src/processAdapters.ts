import { spawn } from "node:child_process";
import type { FailureClass, WorkerResult } from "@waygent/contracts";
import { validateContract } from "@waygent/contracts";
import type { AdapterRequest, ProcessAdapterOutput, ProviderProcessOptions } from "./types";

const defaultTimeoutMs = 30 * 60 * 1000;

export function normalizeProcessOutput(
  provider: "codex" | "claude" | "acp",
  task_id: string,
  candidate_id: string,
  output: ProcessAdapterOutput
): WorkerResult {
  if (output.exitCode !== 0) {
    return failed(task_id, candidate_id, "adapter_crashed", `${provider} exited ${output.exitCode}`);
  }
  try {
    const parsed = parseWorkerOutput(output.stdout) as Partial<WorkerResult>;
    return validateContract<WorkerResult>("runway.worker_result.v1", {
      schema: "runway.worker_result.v1",
      task_id,
      candidate_id,
      status: parsed.status ?? "completed",
      changed_files: parsed.changed_files ?? [],
      summary: parsed.summary ?? `${provider} completed`,
      evidence: { provider, native: parsed.evidence ?? parsed }
    });
  } catch {
    return failed(task_id, candidate_id, "malformed_result", `${provider} produced malformed output`);
  }
}

export function failed(task_id: string, candidate_id: string, failure_class: FailureClass, summary: string): WorkerResult {
  return validateContract<WorkerResult>("runway.worker_result.v1", {
    schema: "runway.worker_result.v1",
    task_id,
    candidate_id,
    status: "failed",
    changed_files: [],
    summary,
    evidence: { failure_class },
    failure_class
  });
}

export async function runProviderProcess(
  provider: "codex" | "claude",
  request: AdapterRequest,
  options: ProviderProcessOptions
): Promise<WorkerResult> {
  return new Promise<WorkerResult>((resolve) => {
    const child = spawn(options.executable, options.args ?? [], {
      cwd: options.cwd,
      env: { ...process.env, ...options.env },
      stdio: ["pipe", "pipe", "pipe"]
    });
    let settled = false;
    let timedOut = false;
    let stdout = "";
    let stderr = "";
    const finish = (result: WorkerResult): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve(result);
    };
    const timeout = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
    }, options.timeout_ms ?? defaultTimeoutMs);
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (error) => {
      finish(failed(request.task_id, request.candidate_id, "adapter_crashed", `${provider} failed to start: ${error.message}`));
    });
    child.on("close", (code) => {
      if (timedOut) {
        finish(failed(request.task_id, request.candidate_id, "timeout", `${provider} timed out after ${options.timeout_ms ?? defaultTimeoutMs}ms`));
        return;
      }
      finish(normalizeProcessOutput(provider, request.task_id, request.candidate_id, { exitCode: code ?? 1, stdout, stderr }));
    });
    child.stdin.end(buildProviderPrompt(provider, request));
  });
}

export function buildProviderPrompt(provider: "codex" | "claude", request: AdapterRequest): string {
  return [
    `You are the ${provider} worker for a Waygent task.`,
    `role: ${request.role ?? "implement"}`,
    `task_id: ${request.task_id}`,
    `candidate_id: ${request.candidate_id}`,
    request.task_packet_path ? `task_packet_path: ${request.task_packet_path}` : "task_packet_path: none",
    "Return only one JSON object matching runway.worker_result.v1 unless the provider wrapper emits JSONL envelopes.",
    "Do not write AgentLens events directly.",
    "Do not apply changes to the source checkout.",
    "Edit only the isolated Waygent worktree.",
    "Obey the task packet write policy.",
    "Required JSON fields: schema, task_id, candidate_id, status, changed_files, summary, evidence.",
    "Task prompt:",
    request.prompt
  ].join("\n");
}

function parseWorkerOutput(stdout: string): unknown {
  const trimmed = stdout.trim();
  const candidates = [
    trimmed,
    ...trimmed
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .reverse()
  ];
  for (const candidate of candidates) {
    const parsed = parseJsonText(candidate);
    if (parsed) return unwrapProviderEnvelope(parsed);
  }
  throw new Error("missing worker result JSON");
}

function unwrapProviderEnvelope(parsed: unknown): unknown {
  if (!parsed || typeof parsed !== "object") return parsed;
  const value = parsed as Record<string, unknown>;
  if (typeof value.result === "string") {
    const nested = parseJsonText(value.result);
    if (nested) return nested;
  }
  if (typeof value.message === "string") {
    const nested = parseJsonText(value.message);
    if (nested) return nested;
  }
  return parsed;
}

function parseJsonText(value: string): unknown | null {
  const trimmed = value.trim();
  const direct = tryParseJson(trimmed);
  if (direct) return direct;
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fenced?.[1]) {
    const parsed = tryParseJson(fenced[1].trim());
    if (parsed) return parsed;
  }
  const start = trimmed.indexOf("{");
  const end = trimmed.lastIndexOf("}");
  if (start >= 0 && end > start) {
    return tryParseJson(trimmed.slice(start, end + 1));
  }
  return null;
}

function tryParseJson(value: string): unknown | null {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}
