import { spawn } from "node:child_process";
import { dirname } from "node:path";
import type { FailureClass, ModelAttestation, TokenUsage, UsageSource, WorkerResult } from "@waygent/contracts";
import { validateContract } from "@waygent/contracts";
import { summarizeProviderStderr } from "./logSummary";
import type { AdapterRequest, ProcessAdapterOutput, ProviderAdapterRunResult, ProviderProcessOptions, ProviderRunMetadata } from "./types";

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
    const { unwrapped, envelope } = parseWorkerOutput(output.stdout);
    const parsed = unwrapped as Partial<WorkerResult>;
    const failure_class = normalizeFailureClass(parsed.failure_class);
    const metadata = metadataFromParsed(provider, parsed, envelope);
    const worker = validateContract<WorkerResult>("runway.worker_result.v1", {
      schema: "runway.worker_result.v1",
      task_id,
      candidate_id,
      status: normalizeWorkerStatus(parsed.status),
      changed_files: parsed.changed_files ?? [],
      summary: parsed.summary ?? `${provider} completed`,
      evidence: { provider, ...((parsed.evidence && typeof parsed.evidence === "object") ? parsed.evidence : {}), native: parsed.evidence ?? parsed },
      ...(failure_class ? { failure_class } : {})
    });
    return withProcessEvidence(worker, output, metadata);
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
    const child = spawn(options.executable, providerProcessArgs(provider, options, cwd, request), {
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

export function providerProcessArgs(provider: "codex" | "claude", options: ProviderProcessOptions, cwd: string | undefined, request: AdapterRequest): string[] {
  const args = options.args ?? [];
  if (provider === "claude") {
    const nextArgs = [...args];
    if (options.executable === "claude") {
      if (cwd && !nextArgs.includes("--add-dir")) {
        const allowedDirs = [cwd];
        if (request.task_packet_path) allowedDirs.push(dirname(request.task_packet_path));
        nextArgs.unshift("--add-dir", ...allowedDirs);
      }
      if (!nextArgs.includes("--permission-mode")) {
        nextArgs.unshift("--permission-mode", "acceptEdits");
      }
    }
    if (options.effort && !nextArgs.includes("--effort")) {
      nextArgs.unshift("--effort", options.effort);
    }
    if (options.model && !nextArgs.includes("--model")) {
      nextArgs.unshift("--model", options.model);
    }
    return nextArgs;
  }
  if (provider !== "codex") return args;
  let nextArgs = [...args];
  if (options.executable === "codex" && options.effort && !nextArgs.includes("--reasoning")) {
    nextArgs = ["--reasoning", options.effort, ...nextArgs];
  }
  if (options.executable === "codex" && options.model && !nextArgs.includes("--model")) {
    nextArgs = ["--model", options.model, ...nextArgs];
  }
  if (!cwd || options.executable !== "codex" || nextArgs.includes("--cd") || nextArgs.includes("-C")) {
    return nextArgs;
  }
  const promptStdinIndex = nextArgs.lastIndexOf("-");
  if (promptStdinIndex >= 0) {
    return [...nextArgs.slice(0, promptStdinIndex), "--cd", cwd, "--skip-git-repo-check", ...nextArgs.slice(promptStdinIndex)];
  }
  return [...nextArgs, "--cd", cwd, "--skip-git-repo-check"];
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

function parseWorkerOutput(stdout: string): { unwrapped: unknown; envelope: unknown | null } {
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
    if (!parsed) continue;
    const unwrapped = unwrapProviderEnvelope(parsed);
    if (isWorkerResultCandidate(unwrapped)) {
      const envelope = unwrapped !== parsed && parsed && typeof parsed === "object" ? parsed : null;
      return { unwrapped, envelope };
    }
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
  if (typeof value.text === "string") {
    const nested = parseJsonText(value.text);
    if (nested) return nested;
  }
  const item = value.item;
  if (item && typeof item === "object") {
    const itemValue = item as Record<string, unknown>;
    if (typeof itemValue.text === "string") {
      const nested = parseJsonText(itemValue.text);
      if (nested) return nested;
    }
  }
  return parsed;
}

function isWorkerResultCandidate(value: unknown): value is Partial<WorkerResult> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return "status" in record || "changed_files" in record || "summary" in record || "failure_class" in record;
}

function parseJsonText(value: string): unknown | null {
  const trimmed = value.trim();

  // 1. Direct JSON. If it parses to a worker_result-shaped object, prefer it.
  const direct = tryParseJson(trimmed);
  if (direct && isWorkerResultCandidate(direct)) return direct;

  // 2. Enumerate every fenced block; prefer `json` label, then unlabeled,
  //    then any other language. The previous non-global regex matched the
  //    FIRST fence in document order, which let a `bash`/`yaml` block ahead
  //    of the real worker_result fence win and drop $3+ of real work.
  const fences = [...trimmed.matchAll(/```(\w+)?\s*([\s\S]*?)```/g)];
  const ordered = [
    ...fences.filter((m) => m[1]?.toLowerCase() === "json"),
    ...fences.filter((m) => !m[1]),
    ...fences.filter((m) => m[1] && m[1].toLowerCase() !== "json")
  ];
  for (const match of ordered) {
    const body = (match[2] ?? "").trim();
    if (body.length === 0) continue;
    const parsed = tryParseJson(body);
    if (parsed && isWorkerResultCandidate(parsed)) return parsed;
  }

  // 3. Balanced-brace fallback: enumerate every string-aware balanced
  //    {...} span and try each, largest first. Replaces the brittle
  //    `indexOf("{") .. lastIndexOf("}")` slice which over-spanned across
  //    unrelated code blocks.
  for (const span of enumerateBalancedBraceSpans(trimmed)) {
    const parsed = tryParseJson(span);
    if (parsed && isWorkerResultCandidate(parsed)) return parsed;
  }

  // 4. Final fallback: return whatever direct parse produced (may be an
  //    envelope which the caller will unwrap), or null.
  if (direct) return direct;
  for (const span of enumerateBalancedBraceSpans(trimmed)) {
    const parsed = tryParseJson(span);
    if (parsed) return parsed;
  }
  return null;
}

function* enumerateBalancedBraceSpans(text: string): Generator<string> {
  type Span = { start: number; end: number };
  const spans: Span[] = [];
  let i = 0;
  while (i < text.length) {
    if (text[i] !== "{") {
      i += 1;
      continue;
    }
    const start = i;
    let depth = 0;
    let inString = false;
    let escaped = false;
    while (i < text.length) {
      const ch = text[i];
      if (escaped) {
        escaped = false;
        i += 1;
        continue;
      }
      if (inString) {
        if (ch === "\\") {
          escaped = true;
        } else if (ch === '"') {
          inString = false;
        }
        i += 1;
        continue;
      }
      if (ch === '"') {
        inString = true;
        i += 1;
        continue;
      }
      if (ch === "{") depth += 1;
      else if (ch === "}") {
        depth -= 1;
        if (depth === 0) {
          spans.push({ start, end: i + 1 });
          i += 1;
          break;
        }
      }
      i += 1;
    }
    if (depth > 0) break;
  }
  spans.sort((a, b) => b.end - b.start - (a.end - a.start));
  for (const s of spans) yield text.slice(s.start, s.end);
}

function tryParseJson(value: string): unknown | null {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function metadataFromParsed(
  provider: "codex" | "claude" | "acp",
  parsed: Partial<WorkerResult>,
  envelope: unknown | null
): ProviderRunMetadata {
  const evidence = parsed.evidence && typeof parsed.evidence === "object" ? parsed.evidence as Record<string, unknown> : {};
  const envelopeUsage = usageFromEnvelope(envelope);
  const evidenceUsage = usageFromEvidence(evidence);
  const usage = envelopeUsage ?? evidenceUsage ?? null;
  const usage_source: UsageSource = envelopeUsage
    ? "provider_json"
    : usageSourceFromEvidence(evidence, provider);
  const envelopeModel = modelFromEnvelope(envelope, provider);
  const evidenceModel = actualModelFromEvidence(evidence);
  const actual_model = evidenceModel.model ? evidenceModel : (envelopeModel ?? evidenceModel);
  return { actual_model, usage, usage_source };
}

function usageFromEnvelope(envelope: unknown): TokenUsage | null {
  if (!envelope || typeof envelope !== "object") return null;
  const record = envelope as Record<string, unknown>;
  const raw = record.usage;
  if (!raw || typeof raw !== "object") return null;
  const u = raw as Record<string, unknown>;
  const input_tokens = numberField(u.input_tokens);
  const output_tokens = numberField(u.output_tokens);
  if (input_tokens === null || output_tokens === null) return null;
  const cached_read_tokens =
    numberField(u.cache_read_input_tokens) ?? numberField(u.cached_read_tokens) ?? 0;
  const cached_write_tokens =
    numberField(u.cache_creation_input_tokens) ?? numberField(u.cached_write_tokens) ?? 0;
  return { input_tokens, output_tokens, cached_read_tokens, cached_write_tokens };
}

function modelFromEnvelope(envelope: unknown, _provider: "codex" | "claude" | "acp"): ModelAttestation | null {
  if (!envelope || typeof envelope !== "object") return null;
  const record = envelope as Record<string, unknown>;
  const modelUsage = record.modelUsage;
  if (modelUsage && typeof modelUsage === "object" && !Array.isArray(modelUsage)) {
    const keys = Object.keys(modelUsage as Record<string, unknown>);
    if (keys.length > 0 && typeof keys[0] === "string" && keys[0].length > 0) {
      return { model: keys[0], reasoning: null, source: "provider_json" };
    }
  }
  if (typeof record.model === "string" && record.model.trim().length > 0) {
    return { model: record.model.trim(), reasoning: null, source: "provider_json" };
  }
  return null;
}

function actualModelFromEvidence(evidence: Record<string, unknown>): ModelAttestation {
  const raw = evidence.actual_model ?? evidence.model;
  if (raw && typeof raw === "object") {
    const record = raw as Record<string, unknown>;
    return {
      model: typeof record.model === "string" ? record.model : null,
      reasoning: typeof record.reasoning === "string" ? record.reasoning : null,
      source: typeof record.source === "string" ? record.source : "provider_json"
    };
  }
  if (typeof raw === "string" && raw.trim().length > 0) {
    return { model: raw.trim(), reasoning: null, source: "provider_json" };
  }
  return { model: null, reasoning: null, source: "unknown" };
}

function usageFromEvidence(evidence: Record<string, unknown>): TokenUsage | null {
  const raw = evidence.usage;
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const usage = {
    input_tokens: numberField(record.input_tokens),
    output_tokens: numberField(record.output_tokens),
    cached_read_tokens: numberField(record.cached_read_tokens),
    cached_write_tokens: numberField(record.cached_write_tokens)
  };
  return usage.input_tokens === null || usage.output_tokens === null || usage.cached_read_tokens === null || usage.cached_write_tokens === null
    ? null
    : usage as TokenUsage;
}

function usageSourceFromEvidence(evidence: Record<string, unknown>, _provider: "codex" | "claude" | "acp"): UsageSource {
  return evidence.usage_source === "provider_json" || evidence.usage_source === "event_stream"
    ? evidence.usage_source
    : usageFromEvidence(evidence)
      ? "provider_json"
      : "unknown";
}

function numberField(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : null;
}

function withProcessEvidence(worker: WorkerResult, output: ProcessAdapterOutput, metadata?: ProviderRunMetadata): ProviderAdapterRunResult {
  const fallbackCompletedAt = new Date().toISOString();
  const completedAt = output.completedAt === undefined ? fallbackCompletedAt : output.completedAt;
  return {
    worker,
    ...(metadata ? { metadata } : { metadata: { actual_model: { model: null, reasoning: null, source: "unknown" }, usage: null, usage_source: "unknown" as const } }),
    process: {
      stdout: output.stdout,
      stderr: output.stderr,
      stderr_summary: summarizeProviderStderr(output.stderr),
      exit_code: output.exitCode,
      timed_out: output.timedOut ?? false,
      started_at: output.startedAt ?? completedAt ?? fallbackCompletedAt,
      completed_at: completedAt,
      event_stream: output.eventStream ?? null
    } as ProviderAdapterRunResult["process"] & { stderr_summary: ReturnType<typeof summarizeProviderStderr> }
  };
}
