import { spawn } from "node:child_process";
import type { FailureClass, WorkerResult } from "@waygent/contracts";
import { validateContract } from "@waygent/contracts";
import type { AdapterRequest, ProcessAdapterOutput, ProviderAdapterRunResult, ProviderProcessOptions } from "./types";

const defaultTimeoutMs = 30 * 60 * 1000;
const failureClasses = new Set<FailureClass>([
  "adapter_crashed",
  "timeout",
  "cancelled",
  "malformed_result",
  "diff_scope_failed",
  "review_changes_requested",
  "review_rejected",
  "verification_failed",
  "merge_conflict",
  "needs_rebase",
  "needs_plan_fix",
  "needs_split",
  "needs_infra_fix",
  "missing_checkpoint",
  "missing_resume_handler",
  "permission_denied",
  "service_unreachable",
  "dependency_missing",
  "environment_blocker",
  "flaky_unconfirmed",
  "command_not_found",
  "dependency_blocked",
  "file_claim_conflict",
  "dirty_source_checkout",
  "unsafe_apply",
  "state_drift",
  "artifact_missing",
  "stale_activity",
  "terminal_rejected"
]);

export function normalizeProcessOutput(
  provider: "codex" | "claude" | "acp",
  task_id: string,
  candidate_id: string,
  output: ProcessAdapterOutput
): ProviderAdapterRunResult {
  if (output.exitCode !== 0) {
    return withProcessEvidence(failed(task_id, candidate_id, "adapter_crashed", `${provider} exited ${output.exitCode}`), output);
  }
  try {
    const parsed = parseWorkerOutput(output.stdout) as Partial<WorkerResult>;
    const failure_class = normalizeFailureClass(parsed.failure_class);
    const worker = validateContract<WorkerResult>("runway.worker_result.v1", {
      schema: "runway.worker_result.v1",
      task_id,
      candidate_id,
      status: normalizeWorkerStatus(parsed.status),
      changed_files: parsed.changed_files ?? [],
      summary: parsed.summary ?? `${provider} completed`,
      evidence: { provider, native: parsed.evidence ?? parsed },
      ...(failure_class ? { failure_class } : {})
    });
    return withProcessEvidence(worker, output);
  } catch {
    return withProcessEvidence(failed(task_id, candidate_id, "malformed_result", `${provider} produced malformed output`), output);
  }
}

function normalizeWorkerStatus(status: unknown): WorkerResult["status"] {
  if (status === undefined) return "completed";
  if (status === "success") return "completed";
  if (status === "completed" || status === "failed" || status === "blocked") return status;
  throw new Error(`unknown worker status: ${String(status)}`);
}

function normalizeFailureClass(value: unknown): FailureClass | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value === "string" && failureClasses.has(value as FailureClass)) return value as FailureClass;
  throw new Error(`unknown failure_class: ${String(value)}`);
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
): Promise<ProviderAdapterRunResult> {
  return new Promise<ProviderAdapterRunResult>((resolve) => {
    const cwd = options.cwd ?? request.cwd;
    const startedAt = new Date().toISOString();
    const child = spawn(options.executable, providerProcessArgs(provider, options, cwd), {
      cwd,
      env: { ...process.env, ...options.env, ...(cwd ? { PWD: cwd } : {}) },
      stdio: ["pipe", "pipe", "pipe"]
    });
    let settled = false;
    let timedOut = false;
    let stdout = "";
    let stderr = "";
    const finish = (result: ProviderAdapterRunResult): void => {
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
      const summary = `${provider} failed to start: ${error.message}`;
      stderr = stderr ? `${stderr}\n${summary}` : summary;
      finish(
        withProcessEvidence(failed(request.task_id, request.candidate_id, "adapter_crashed", summary), {
          exitCode: null,
          stdout,
          stderr,
          timedOut: false,
          startedAt,
          completedAt: new Date().toISOString()
        })
      );
    });
    child.on("close", (code) => {
      const completedAt = new Date().toISOString();
      if (timedOut) {
        finish(
          withProcessEvidence(failed(request.task_id, request.candidate_id, "timeout", `${provider} timed out after ${options.timeout_ms ?? defaultTimeoutMs}ms`), {
            exitCode: code,
            stdout,
            stderr,
            timedOut: true,
            startedAt,
            completedAt
          })
        );
        return;
      }
      finish(
        normalizeProcessOutput(provider, request.task_id, request.candidate_id, {
          exitCode: code ?? 1,
          stdout,
          stderr,
          timedOut: false,
          startedAt,
          completedAt
        })
      );
    });
    child.stdin.on("error", () => {});
    child.stdin.end(buildProviderPrompt(provider, request));
  });
}

function providerProcessArgs(provider: "codex" | "claude", options: ProviderProcessOptions, cwd: string | undefined): string[] {
  const args = options.args ?? [];
  if (provider !== "codex" || !cwd || options.executable !== "codex" || args.includes("--cd") || args.includes("-C")) {
    return args;
  }
  const promptStdinIndex = args.lastIndexOf("-");
  if (promptStdinIndex >= 0) {
    return [...args.slice(0, promptStdinIndex), "--cd", cwd, "--skip-git-repo-check", ...args.slice(promptStdinIndex)];
  }
  return [...args, "--cd", cwd, "--skip-git-repo-check"];
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

function withProcessEvidence(worker: WorkerResult, output: ProcessAdapterOutput): ProviderAdapterRunResult {
  const fallbackCompletedAt = new Date().toISOString();
  const completedAt = output.completedAt === undefined ? fallbackCompletedAt : output.completedAt;
  return {
    worker,
    process: {
      stdout: output.stdout,
      stderr: output.stderr,
      exit_code: output.exitCode,
      timed_out: output.timedOut ?? false,
      started_at: output.startedAt ?? completedAt ?? fallbackCompletedAt,
      completed_at: completedAt,
      event_stream: output.eventStream ?? null
    }
  };
}
