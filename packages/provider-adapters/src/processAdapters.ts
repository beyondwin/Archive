import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { basename, dirname } from "node:path";
import type { FailureClass, ModelAttestation, ProviderRole, TokenUsage, UsageSource, WorkerResult } from "@waygent/contracts";
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

const knownProviderRoles: ReadonlySet<ProviderRole> = new Set<ProviderRole>([
  "implement",
  "review",
  "fix",
  "verify_assist"
]);

const HOST_ENV_KEYS_TO_DROP = ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_PROJECT_DIR"] as const;

export function normalizeProcessOutput(
  provider: "codex" | "claude" | "acp",
  task_id: string,
  candidate_id: string,
  output: ProcessAdapterOutput
): ProviderAdapterRunResult {
  if (output.exitCode !== 0) {
    const failureMetadata = metadataFromStreamOnly(provider, output.stdout, output.stderr);
    return withProcessEvidence(failed(task_id, candidate_id, "adapter_crashed", `${provider} exited ${output.exitCode}`), output, failureMetadata);
  }
  try {
    const parsedOutput = parseWorkerOutput(output.stdout);
    const parsed = parsedOutput.unwrapped as Partial<WorkerResult>;
    const failure_class = normalizeFailureClass(parsed.failure_class);
    const metadata = metadataFromParsed(provider, parsed, parsedOutput.envelope, parsedOutput.systemInit, output.stderr);
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
    const metadata = metadataFromStreamOnly(provider, output.stdout, output.stderr);
    return withProcessEvidence(failed(task_id, candidate_id, "malformed_result", `${provider} produced malformed output`), output, metadata);
  }
}

function normalizeWorkerStatus(status: unknown): WorkerResult["status"] {
  if (status === undefined) return "completed";
  if (typeof status !== "string") {
    throw new Error(`unknown worker status: ${String(status)}`);
  }
  const lowered = status.trim().toLowerCase();
  if (lowered === "completed" || lowered === "failed" || lowered === "blocked") return lowered;
  if (
    lowered === "success" ||
    lowered === "succeeded" ||
    lowered === "complete" ||
    lowered === "implemented" ||
    lowered === "done" ||
    lowered === "ok" ||
    lowered === "ready" ||
    lowered === "ready_for_review" ||
    lowered === "ready-for-review" ||
    lowered === "needs_verification" ||
    lowered === "needs-verification" ||
    lowered === "ready_for_verification" ||
    lowered === "ready-for-verification"
  ) {
    return "completed";
  }
  if (lowered === "failure" || lowered === "error" || lowered === "errored") return "failed";
  if (lowered === "halted" || lowered === "stopped" || lowered === "paused") return "blocked";
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

function resolveTimeoutMs(options: ProviderProcessOptions, role: ProviderRole | undefined): number {
  if (role && options.timeout_ms_by_role) {
    const override = options.timeout_ms_by_role[role];
    if (typeof override === "number" && Number.isFinite(override) && override > 0) return override;
  }
  if (typeof options.timeout_ms === "number" && Number.isFinite(options.timeout_ms) && options.timeout_ms > 0) {
    return options.timeout_ms;
  }
  return defaultTimeoutMs;
}

export function buildSpawnEnv(
  parentEnv: NodeJS.ProcessEnv,
  optionEnv: Record<string, string> | undefined,
  cwd: string | undefined
): Record<string, string> {
  const keepHostEnv = parentEnv.WAYGENT_KEEP_HOST_ENV === "1";
  const shouldSanitize = !keepHostEnv && (parentEnv.CLAUDECODE === "1" || typeof parentEnv.CLAUDE_CODE_ENTRYPOINT === "string");
  const next: Record<string, string> = {};
  for (const [key, value] of Object.entries(parentEnv)) {
    if (value === undefined) continue;
    if (shouldSanitize && (HOST_ENV_KEYS_TO_DROP as readonly string[]).includes(key)) continue;
    next[key] = value;
  }
  if (optionEnv) {
    for (const [key, value] of Object.entries(optionEnv)) {
      next[key] = value;
    }
  }
  if (cwd) next.PWD = cwd;
  return next;
}

export async function runProviderProcess(
  provider: "codex" | "claude",
  request: AdapterRequest,
  options: ProviderProcessOptions
): Promise<ProviderAdapterRunResult> {
  return new Promise<ProviderAdapterRunResult>((resolve) => {
    const cwd = normalizeProcessCwd(options.cwd ?? request.cwd);
    const startedAt = new Date().toISOString();
    const { args: spawnArgs, warnings } = providerProcessArgsWithWarnings(provider, options, cwd, request);
    const child = spawn(options.executable, spawnArgs, {
      cwd,
      env: buildSpawnEnv(process.env, options.env, cwd),
      stdio: ["pipe", "pipe", "pipe"]
    });
    const usesStreamJson = provider === "claude" && spawnArgs.includes("stream-json");
    let settled = false;
    let timedOut = false;
    let stdout = "";
    let stderr = warnings.length > 0 ? warnings.map((line) => `${line}\n`).join("") : "";
    const finish = (result: ProviderAdapterRunResult): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve(result);
    };
    const timeout = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
    }, resolveTimeoutMs(options, request.role));
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
      const eventStream = usesStreamJson ? stdout : null;
      if (timedOut) {
        finish(
          withProcessEvidence(failed(request.task_id, request.candidate_id, "timeout", `${provider} timed out after ${resolveTimeoutMs(options, request.role)}ms`), {
            exitCode: code,
            stdout,
            stderr,
            timedOut: true,
            startedAt,
            completedAt,
            eventStream
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
          completedAt,
          eventStream
        })
      );
    });
    child.stdin.on("error", () => {});
    child.stdin.end(buildProviderStdinPrompt(provider, request));
  });
}

function normalizeProcessCwd(cwd: string | undefined): string | undefined {
  if (!cwd || existsSync(cwd)) return cwd;
  try {
    const decoded = decodeURIComponent(cwd);
    return existsSync(decoded) ? decoded : cwd;
  } catch {
    return cwd;
  }
}

export interface ProviderProcessArgsResult {
  args: string[];
  warnings: string[];
}

export function providerProcessArgsWithWarnings(
  provider: "codex" | "claude",
  options: ProviderProcessOptions,
  cwd: string | undefined,
  request: AdapterRequest
): ProviderProcessArgsResult {
  const args = options.args ?? [];
  const warnings: string[] = [];
  if (provider === "claude") {
    const nextArgs = [...args];
    const isClaudeCli = isProviderCliExecutable("claude", options.executable);
    if (isClaudeCli) {
      if (cwd && !nextArgs.includes("--add-dir")) {
        const allowedDirs = [cwd];
        if (request.task_packet_path) allowedDirs.push(dirname(request.task_packet_path));
        nextArgs.unshift("--add-dir", ...allowedDirs);
      }
      const role = resolveRole(request.role, warnings);
      applyClaudeRoleArgs(nextArgs, role);
      if (options.settings_path && !nextArgs.includes("--settings")) {
        nextArgs.push("--settings", options.settings_path);
      }
      if (options.mcp_config_path && !nextArgs.includes("--mcp-config")) {
        nextArgs.push("--mcp-config", options.mcp_config_path);
      }
      const systemPrompt = buildProviderSystemPrompt(role);
      if (systemPrompt && !nextArgs.includes("--append-system-prompt")) {
        nextArgs.push("--append-system-prompt", systemPrompt);
      }
      if (options.resume_session_id) {
        if (!nextArgs.includes("--resume")) {
          nextArgs.push("--resume", options.resume_session_id);
        }
      } else if (options.session_id) {
        if (!nextArgs.includes("--session-id")) {
          nextArgs.push("--session-id", options.session_id);
        }
      }
    }
    if (isClaudeCli && options.effort && !nextArgs.includes("--effort")) {
      nextArgs.unshift("--effort", options.effort);
    }
    if (isClaudeCli && options.model && !nextArgs.includes("--model")) {
      nextArgs.unshift("--model", options.model);
    }
    return { args: nextArgs, warnings };
  }
  if (provider !== "codex") return { args, warnings };
  let nextArgs = [...args];
  const isCodexCli = isProviderCliExecutable("codex", options.executable);
  if (isCodexCli && options.effort && !nextArgs.includes("--reasoning")) {
    nextArgs = ["--reasoning", options.effort, ...nextArgs];
  }
  if (isCodexCli && options.model && !nextArgs.includes("--model")) {
    nextArgs = ["--model", options.model, ...nextArgs];
  }
  if (!cwd || !isCodexCli || nextArgs.includes("--cd") || nextArgs.includes("-C")) {
    return { args: nextArgs, warnings };
  }
  const promptStdinIndex = nextArgs.lastIndexOf("-");
  if (promptStdinIndex >= 0) {
    return {
      args: [...nextArgs.slice(0, promptStdinIndex), "--cd", cwd, "--skip-git-repo-check", ...nextArgs.slice(promptStdinIndex)],
      warnings
    };
  }
  return { args: [...nextArgs, "--cd", cwd, "--skip-git-repo-check"], warnings };
}

export function providerProcessArgs(provider: "codex" | "claude", options: ProviderProcessOptions, cwd: string | undefined, request: AdapterRequest): string[] {
  return providerProcessArgsWithWarnings(provider, options, cwd, request).args;
}

function resolveRole(role: ProviderRole | undefined, warnings: string[]): ProviderRole {
  if (role === undefined) return "implement";
  if (knownProviderRoles.has(role)) return role;
  warnings.push(`waygent: unknown provider role '${String(role)}' — falling back to 'implement'`);
  return "implement";
}

function applyClaudeRoleArgs(nextArgs: string[], role: ProviderRole): void {
  const hasPermissionMode = nextArgs.includes("--permission-mode");
  if (role === "review") {
    if (!hasPermissionMode) nextArgs.unshift("--permission-mode", "plan");
    if (!nextArgs.includes("--disallowedTools")) {
      nextArgs.unshift("--disallowedTools", "Edit,Write,MultiEdit");
    }
    return;
  }
  if (role === "verify_assist") {
    if (!hasPermissionMode) nextArgs.unshift("--permission-mode", "acceptEdits");
    if (!nextArgs.includes("--allowedTools")) {
      nextArgs.unshift("--allowedTools", "Bash,Read,Glob,Grep");
    }
    return;
  }
  // implement / fix / undefined-resolved-to-implement
  if (!hasPermissionMode) nextArgs.unshift("--permission-mode", "acceptEdits");
}

function isProviderCliExecutable(provider: "codex" | "claude", executable: string): boolean {
  const name = basename(executable).replace(/\.(cmd|exe|bat)$/i, "");
  return name === provider;
}

export function buildProviderSystemPrompt(role: ProviderRole): string {
  const roleLine = `You are the Waygent worker with role: ${role}.`;
  return [
    roleLine,
    "Return only one JSON object matching runway.worker_result.v1 unless the provider wrapper emits JSONL envelopes.",
    "Do not write AgentLens events directly.",
    "Do not apply changes to the source checkout.",
    "Edit only the isolated Waygent worktree.",
    "Obey the task packet write policy.",
    "Required JSON fields: schema, task_id, candidate_id, status, changed_files, summary, evidence."
  ].join("\n");
}

export function buildProviderUserPrompt(provider: "codex" | "claude", request: AdapterRequest): string {
  const retryPrefix = request.retry_context ? buildRetryPromptPrefix(request.retry_context) : null;
  const body = [
    `Provider: ${provider}.`,
    `role: ${request.role ?? "implement"}`,
    `task_id: ${request.task_id}`,
    `candidate_id: ${request.candidate_id}`,
    request.task_packet_path ? `task_packet_path: ${request.task_packet_path}` : "task_packet_path: none",
    "Task prompt:",
    request.prompt
  ].join("\n");
  return retryPrefix ? `${retryPrefix}\n\n${body}` : body;
}

// What we actually pipe to stdin for each provider. Claude moves the contract
// reminder block out of stdin and into --append-system-prompt; Codex still
// receives the legacy combined prompt because it has no equivalent surface.
function buildProviderStdinPrompt(provider: "codex" | "claude", request: AdapterRequest): string {
  if (provider === "claude") return buildProviderUserPrompt(provider, request);
  const legacy = buildProviderPrompt(provider, request);
  if (!request.retry_context) return legacy;
  return `${buildRetryPromptPrefix(request.retry_context)}\n\n${legacy}`;
}

export function buildRetryPromptPrefix(context: { failure_class: FailureClass; stderr_summary?: string }): string {
  const summary = (context.stderr_summary ?? "").slice(0, 300);
  return `Prior attempt failed: ${context.failure_class}. stderr summary: ${summary}. Fix and respond with the same runway.worker_result.v1 contract.`;
}

// Back-compat: kept for tests / callers that still expect the legacy combined prompt.
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

export interface ParsedWorkerOutput {
  unwrapped: unknown;
  envelope: unknown | null;
  systemInit: Record<string, unknown> | null;
}

function parseWorkerOutput(stdout: string): ParsedWorkerOutput {
  const trimmed = stdout.trim();
  const lines = trimmed.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  let systemInit: Record<string, unknown> | null = null;
  let resultEvent: Record<string, unknown> | null = null;
  for (const line of lines) {
    const parsed = tryParseJson(line);
    if (!parsed || typeof parsed !== "object") continue;
    const record = parsed as Record<string, unknown>;
    if (record.type === "system" && record.subtype === "init" && !systemInit) {
      systemInit = record;
    } else if (record.type === "result") {
      resultEvent = record;
    }
  }
  if (resultEvent) {
    const unwrapped = unwrapProviderEnvelope(resultEvent);
    if (isWorkerResultCandidate(unwrapped)) {
      return { unwrapped, envelope: resultEvent, systemInit };
    }
  }

  // Legacy / single-blob path.
  const candidates = [
    trimmed,
    ...lines.slice().reverse()
  ];
  for (const candidate of candidates) {
    const parsed = parseJsonText(candidate);
    if (!parsed) continue;
    const unwrapped = unwrapProviderEnvelope(parsed);
    if (isWorkerResultCandidate(unwrapped)) {
      const envelope = unwrapped !== parsed && parsed && typeof parsed === "object" ? parsed : null;
      return { unwrapped, envelope, systemInit };
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

  const direct = tryParseJson(trimmed);
  if (direct && isWorkerResultCandidate(direct)) return direct;

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

  for (const span of enumerateBalancedBraceSpans(trimmed)) {
    const parsed = tryParseJson(span);
    if (parsed && isWorkerResultCandidate(parsed)) return parsed;
  }

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

function metadataFromStreamOnly(
  provider: "codex" | "claude" | "acp",
  stdout: string,
  stderr: string
): ProviderRunMetadata {
  let systemInit: Record<string, unknown> | null = null;
  const trimmed = stdout.trim();
  if (trimmed.length > 0) {
    const lines = trimmed.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    for (const line of lines) {
      const parsed = tryParseJson(line);
      if (parsed && typeof parsed === "object") {
        const record = parsed as Record<string, unknown>;
        if (record.type === "system" && record.subtype === "init") {
          systemInit = record;
          break;
        }
      }
    }
  }
  const session_id = sessionIdFromInit(systemInit);
  const resume_session_missing = detectResumeSessionMissing(stderr);
  const meta: ProviderRunMetadata = {
    actual_model: modelFromSystemInit(systemInit) ?? { model: null, reasoning: null, source: "unknown" },
    usage: null,
    usage_source: "unknown"
  };
  if (session_id !== null) meta.session_id = session_id;
  if (resume_session_missing) meta.resume_session_missing = true;
  return meta;
}

function metadataFromParsed(
  provider: "codex" | "claude" | "acp",
  parsed: Partial<WorkerResult>,
  envelope: unknown | null,
  systemInit: Record<string, unknown> | null,
  stderr: string
): ProviderRunMetadata {
  const evidence = parsed.evidence && typeof parsed.evidence === "object" ? parsed.evidence as Record<string, unknown> : {};
  const envelopeUsage = usageFromEnvelope(envelope);
  const evidenceUsage = usageFromEvidence(evidence);
  const usage = envelopeUsage ?? evidenceUsage ?? null;
  const usage_source: UsageSource = envelopeUsage
    ? "provider_json"
    : usageSourceFromEvidence(evidence, provider);
  const systemInitModel = modelFromSystemInit(systemInit);
  const envelopeModel = modelFromEnvelope(envelope, provider);
  const evidenceModel = actualModelFromEvidence(evidence);
  let actual_model: ModelAttestation;
  if (evidenceModel.model) {
    actual_model = evidenceModel;
  } else if (systemInitModel) {
    actual_model = systemInitModel;
  } else if (envelopeModel) {
    actual_model = envelopeModel;
  } else {
    actual_model = evidenceModel;
  }
  const session_id = sessionIdFromInit(systemInit);
  const resume_session_missing = detectResumeSessionMissing(stderr);
  const meta: ProviderRunMetadata = { actual_model, usage, usage_source };
  if (session_id !== null) meta.session_id = session_id;
  if (resume_session_missing) meta.resume_session_missing = true;
  return meta;
}

function sessionIdFromInit(systemInit: Record<string, unknown> | null): string | null {
  if (!systemInit) return null;
  const value = systemInit.session_id;
  return typeof value === "string" && value.length > 0 ? value : null;
}

function detectResumeSessionMissing(stderr: string): boolean {
  if (!stderr) return false;
  return /session.*not.*found/i.test(stderr);
}

function modelFromSystemInit(systemInit: Record<string, unknown> | null): ModelAttestation | null {
  if (!systemInit) return null;
  const model = systemInit.model;
  if (typeof model === "string" && model.trim().length > 0) {
    return { model: model.trim(), reasoning: null, source: "provider_json" };
  }
  return null;
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
